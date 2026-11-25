import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.user import User

hash_context = CryptContext(schemes=["argon2"], deprecated="auto")

# Verified against when an email is unknown, so login timing doesn't reveal which emails exist.
_DUMMY_HASH = hash_context.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return hash_context.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    if hashed_password is None:
        hash_context.verify(plain_password, _DUMMY_HASH)
        return False
    return hash_context.verify(plain_password, hashed_password)


def generate_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return hash_context.hash(code)


def verify_otp_code(code: str, code_hash: str) -> bool:
    return hash_context.verify(code, code_hash)


def create_token(subject: str, scope: str, expires_delta: timedelta, extra_claims: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "scope": scope, "iss": settings.TOKEN_ISSUER, "iat": now, "exp": now + expires_delta}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.TOKEN_SIGNING_KEY, algorithm=settings.TOKEN_ALGORITHM)


def create_access_token(user: "User") -> str:
    # full_name/avatar_url are already public to anyone holding this token (see GET /auth/user),
    # so embedding them costs nothing in exposure and lets other services show "who commented"
    # without a new lookup endpoint or a sync call back to us on every read.
    return create_token(
        subject=str(user.id),
        scope="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TTL_MINUTES),
        extra_claims={"full_name": user.full_name, "avatar_url": user.avatar_url},
    )


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()   # 64 hex chars -> refresh_tokens.token_hash String(64)


def as_utc(value: datetime) -> datetime:
    """Treat naive datetimes (e.g. from backends that drop tzinfo) as UTC so they compare safely."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
