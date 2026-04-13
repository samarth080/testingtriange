"""
Async SQLAlchemy engine and session factory.

Usage in FastAPI routes:
    from app.core.database import get_db
    async def my_route(db: AsyncSession = Depends(get_db)): ...

Usage in Celery tasks (sync context):
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        ...
    # Then wrap with asyncio.run() in the Celery task
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,  # Reconnect if Postgres dropped the connection
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,  # Don't expire objects after commit — we read them after
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an AsyncSession, closes it when the request ends."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
