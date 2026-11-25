import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.core import REFRESH_COOKIE, clear_session_cookies, set_session_cookies
from app.core.rate_limit import limiter
from app.core.security import (
    as_utc,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.db.session import get_db
from app.models.otp import OTPPurpose
from app.models.refresh_token import RefreshToken
from app.models.user import AccountStatus, AuthProvider, User, UserRole
from app.schemas.auth import (
    CurrentUserResponse,
    ForgotPasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    MessageResponse,
    PublicUserResponse,
    ResendCodeRequest,
    ResetPasswordRequest,
    SessionResponse,
    SignupRequest,
    SignupResponse,
    VerifyEmailRequest,
)
from app.services.google_identity import verify_google_id_token
from app.services.otp_service import consume_otp, issue_otp, issue_otp_with_cooldown
from app.services.session_service import start_session

router = APIRouter(prefix="/auth", tags=["auth"])

# Same reply whether or not the address belongs to an account, so the endpoints can't be used to probe for users.
GENERIC_CODE_SENT = "If an account exists for that email, a code has been sent."


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()


def _session_response(user: User, message: str, is_new_user: bool = False) -> SessionResponse:
    return SessionResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        account_status=user.account_status,
        is_new_user=is_new_user,
        message=message,
    )


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def signup(request: Request, payload: SignupRequest, db: AsyncSession = Depends(get_db)):
    if await _get_user_by_email(db, payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        role=UserRole.CUSTOMER,
        auth_provider=AuthProvider.LOCAL,
        account_status=AccountStatus.PENDING_EMAIL_VERIFICATION,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    await db.refresh(user)

    await issue_otp(user, OTPPurpose.EMAIL_VERIFICATION, db)

    return SignupResponse(
        id=user.id,
        email=user.email,
        account_status=user.account_status,
        detail="Account created. Enter the code sent to your email to verify it.",
    )


@router.post("/verify-email", response_model=SessionResponse)
@limiter.limit("10/minute")
async def verify_email(
    request: Request, payload: VerifyEmailRequest, response: Response, db: AsyncSession = Depends(get_db)
):
    user = await _get_user_by_email(db, payload.email)
    if user is None or user.account_status != AccountStatus.PENDING_EMAIL_VERIFICATION:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code")

    await consume_otp(user, OTPPurpose.EMAIL_VERIFICATION, payload.code, db)
    user.account_status = AccountStatus.ACTIVE
    await db.commit()

    await start_session(user, response, db)
    return _session_response(user, "Email verified. You're now logged in.")


@router.post("/resend-verification-code", response_model=MessageResponse)
@limiter.limit("5/minute")
async def resend_verification_code(request: Request, payload: ResendCodeRequest, db: AsyncSession = Depends(get_db)):
    user = await _get_user_by_email(db, payload.email)
    if user and user.account_status == AccountStatus.PENDING_EMAIL_VERIFICATION:
        await issue_otp_with_cooldown(user, OTPPurpose.EMAIL_VERIFICATION, db)
    return MessageResponse(detail=GENERIC_CODE_SENT)


@router.post("/login", response_model=SessionResponse)
@limiter.limit("10/minute")
async def login(request: Request, payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await _get_user_by_email(db, payload.email)

    if not verify_password(payload.password, user.hashed_password if user else None) or user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if user.account_status == AccountStatus.PENDING_EMAIL_VERIFICATION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Please verify your email before logging in")

    await start_session(user, response, db)
    return _session_response(user, "Login successful")


@router.post("/google", response_model=SessionResponse)
@limiter.limit("10/minute")
async def google_auth(
    request: Request, payload: GoogleAuthRequest, response: Response, db: AsyncSession = Depends(get_db)
):
    """Sign up or log in with a Google ID token (the `credential` from Google Identity Services)."""
    identity = await verify_google_id_token(payload.id_token)

    user = (await db.execute(select(User).where(User.google_sub == identity.sub))).scalar_one_or_none()
    is_new_user = False

    if user is None:
        user = await _get_user_by_email(db, identity.email)
        if user is not None:
            # Link Google to the existing account. Google has verified the address, so the account is now trusted;
            # if it was still unverified, drop the password set at signup since its owner was never proven.
            user.google_sub = identity.sub
            user.avatar_url = user.avatar_url or identity.picture
            if user.account_status == AccountStatus.PENDING_EMAIL_VERIFICATION:
                user.account_status = AccountStatus.ACTIVE
                user.hashed_password = None
                user.auth_provider = AuthProvider.GOOGLE
        else:
            user = User(
                email=identity.email,
                full_name=identity.name,
                avatar_url=identity.picture,
                google_sub=identity.sub,
                role=UserRole.CUSTOMER,
                auth_provider=AuthProvider.GOOGLE,
                account_status=AccountStatus.ACTIVE,
            )
            db.add(user)
            is_new_user = True

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Account conflict. Please try again.")

    await start_session(user, response, db)
    return _session_response(user, "Signed up with Google" if is_new_user else "Login successful", is_new_user)


@router.post("/refresh", response_model=MessageResponse)
@limiter.limit("30/minute")
async def refresh_session(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(REFRESH_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    # Row lock so two concurrent refreshes with the same token can't both succeed.
    stored = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token)).with_for_update()
        )
    ).scalar_one_or_none()
    if stored is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if stored.is_revoked:
        # A rotated-out token was replayed: assume theft and kill the whole family.
        await db.execute(update(RefreshToken).where(RefreshToken.family_id == stored.family_id).values(is_revoked=True))
        await db.commit()
        clear_session_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalid. Please log in again.")

    if datetime.now(timezone.utc) > as_utc(stored.expires_at):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = (await db.execute(select(User).where(User.id == stored.user_id))).scalar_one_or_none()
    if user is None or user.account_status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    stored.is_revoked = True
    new_raw_token = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=stored.user_id,
            family_id=stored.family_id,
            token_hash=hash_refresh_token(new_raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TTL_DAYS),
        )
    )
    await db.commit()

    set_session_cookies(response, create_access_token(user), new_raw_token)
    return MessageResponse(detail="Session refreshed")


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw_token = request.cookies.get(REFRESH_COOKIE)
    if raw_token:
        await db.execute(
            update(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token)).values(is_revoked=True)
        )
        await db.commit()

    clear_session_cookies(response)
    return MessageResponse(detail="Logged out")


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit("5/minute")
async def forgot_password(request: Request, payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    user = await _get_user_by_email(db, payload.email)
    if user and user.account_status == AccountStatus.ACTIVE:
        await issue_otp_with_cooldown(user, OTPPurpose.PASSWORD_RESET, db)
    return MessageResponse(detail=f"OTP sent to your email, {payload.email}")
    # return MessageResponse(detail=GENERIC_CODE_SENT)


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit("10/minute")
async def reset_password(request: Request, payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    user = await _get_user_by_email(db, payload.email)
    if user is None or user.account_status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code")

    await consume_otp(user, OTPPurpose.PASSWORD_RESET, payload.code, db)

    user.hashed_password = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    await db.execute(
        update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.is_revoked.is_(False)).values(is_revoked=True)
    )
    await db.commit()

    return MessageResponse(detail="Password reset successful. Please log in again.")


@router.get("/user", response_model=CurrentUserResponse)
@limiter.limit("60/minute")
async def get_user(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Get the caller's own full profile."""
    return current_user


@router.get("/user/{user_id}", response_model=PublicUserResponse)
@limiter.limit("60/minute")
async def get_user_by_id(
    request: Request,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get public display data (id, full_name, avatar_url) of an ACTIVE customer by ID."""
    target = (
        await db.execute(select(User).where(User.id == user_id, User.account_status == AccountStatus.ACTIVE))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return PublicUserResponse.model_validate(target)
