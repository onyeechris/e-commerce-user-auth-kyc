import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import as_utc, generate_otp_code, hash_otp, verify_otp_code
from app.models.otp import OTP, OTPPurpose
from app.models.user import User
from app.services.mailer import send_otp_email

logger = logging.getLogger(__name__)

INVALID_CODE = "Invalid or expired code"


async def _latest_active_otp(user: User, purpose: OTPPurpose, db: AsyncSession, lock: bool = False) -> OTP | None:
    stmt = (
        select(OTP)
        .where(OTP.user_id == user.id, OTP.purpose == purpose, OTP.is_used.is_(False))
        .order_by(OTP.created_at.desc())
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().first()


async def issue_otp(user: User, purpose: OTPPurpose, db: AsyncSession) -> None:
    await db.execute(
        update(OTP).where(OTP.user_id == user.id, OTP.purpose == purpose, OTP.is_used.is_(False)).values(is_used=True)
    )

    code = generate_otp_code()
    db.add(
        OTP(
            user_id=user.id,
            code_hash=hash_otp(code),
            purpose=purpose,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.OTP_TTL_MINUTES),
        )
    )
    await db.commit()

    try:
        await run_in_threadpool(send_otp_email, user.email, code, purpose.value)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send %s OTP email to user %s", purpose.value, user.id)


async def issue_otp_with_cooldown(user: User, purpose: OTPPurpose, db: AsyncSession) -> bool:
    """Issue a code unless one was sent within the cooldown. Returns whether a new code went out."""
    latest = await _latest_active_otp(user, purpose, db)
    if latest is not None:
        elapsed = datetime.now(timezone.utc) - as_utc(latest.created_at)
        if elapsed < timedelta(seconds=settings.OTP_RESEND_WAIT_SECONDS):
            return False
    await issue_otp(user, purpose, db)
    return True


async def consume_otp(user: User, purpose: OTPPurpose, code: str, db: AsyncSession) -> None:
    """Validate and burn a code. Raises 400 with a single generic message for every failure mode."""
    otp = await _latest_active_otp(user, purpose, db, lock=True)
    if otp is None or datetime.now(timezone.utc) > as_utc(otp.expires_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE)

    if otp.attempts >= settings.OTP_ATTEMPT_LIMIT:
        otp.is_used = True
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE)

    if not verify_otp_code(code, otp.code_hash):
        otp.attempts += 1
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=INVALID_CODE)

    otp.is_used = True  # committed by the caller together with its own changes
