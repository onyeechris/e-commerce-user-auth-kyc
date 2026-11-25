import os

os.environ.update(
    SERVICE_NAME="test",
    ENVIRONMENT="test",
    POSTGRES_DSN="sqlite+aiosqlite:///:memory:",
    TOKEN_SIGNING_KEY="test-secret",
    GOOGLE_OAUTH_CLIENT_ID="test-client-id",
    MAIL_API_KEY="x",
    MAIL_SENDER_EMAIL="noreply@example.com",
    ALLOWED_ORIGINS="http://localhost:3000",
    SESSION_COOKIE_SECURE="False",
    RATE_LIMIT_ENABLED="False",
)

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def sent_codes(monkeypatch):
    """Captures OTPs instead of emailing them: {(email, purpose): code}."""
    codes: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "app.services.otp_service.send_otp_email",
        lambda email, code, purpose: codes.__setitem__((email, purpose), code),
    )
    return codes


@pytest_asyncio.fixture
async def client(sent_codes):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()
