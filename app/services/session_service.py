import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.core import set_session_cookies
from app.core.security import create_access_token, generate_refresh_token, hash_refresh_token
from app.models.refresh_token import RefreshToken
from app.models.user import User


async def start_session(user: User, response: Response, db: AsyncSession) -> None:
    access_token = create_access_token(user)
    refresh_plain = generate_refresh_token()

    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=uuid.uuid4(),
            token_hash=hash_refresh_token(refresh_plain),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TTL_DAYS),
        )
    )
    await db.commit()

    set_session_cookies(response, access_token, refresh_plain)
