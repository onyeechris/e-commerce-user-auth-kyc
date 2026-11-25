import uuid

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.core import ACCESS_COOKIE
from app.core.security import as_utc
from app.db.session import get_db
from app.models.user import AccountStatus, User


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = jwt.decode(
            token, settings.TOKEN_SIGNING_KEY, algorithms=[settings.TOKEN_ALGORITHM], issuer=settings.TOKEN_ISSUER
        )
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    if payload.get("scope") != "access":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token scope")

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.account_status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is not active")

    # A password reset invalidates every access token issued before it. JWT "iat" has whole-second
    # precision, so the reset time is truncated to the second too (a token minted in the same second
    # as the reset is still accepted).
    if user.password_changed_at is not None:
        if payload.get("iat", 0) < int(as_utc(user.password_changed_at).timestamp()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired. Please log in again.")

    return user
