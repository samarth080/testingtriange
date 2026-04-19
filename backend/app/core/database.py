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
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args={"statement_cache_size": 0},  # Required for Supabase pgbouncer in transaction mode
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,  # Don't expire objects after commit — we read them after
)


def make_worker_session() -> async_sessionmaker:
    """
    Create a fresh session factory with NullPool for use in Celery tasks.

    Celery forks worker processes — connection pools created in the parent
    process have asyncio futures attached to the parent's event loop, which
    causes 'Future attached to a different loop' errors in child processes.
    NullPool avoids this by never reusing connections across asyncio.run() calls.
    """
    worker_engine = create_async_engine(
        settings.database_url, poolclass=NullPool, pool_pre_ping=False,
        connect_args={"statement_cache_size": 0},
    )
    return async_sessionmaker(worker_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an AsyncSession, closes it when the request ends."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
