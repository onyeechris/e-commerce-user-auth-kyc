from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# asyncpg takes `ssl` (not `sslmode`); "require" encrypts without verifying the server certificate.
_connect_args = {"ssl": "require"} if settings.DB_REQUIRE_SSL else {}

engine = create_async_engine(
    settings.POSTGRES_DSN,
    echo=(settings.ENVIRONMENT == "development"),
    pool_pre_ping=True,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
