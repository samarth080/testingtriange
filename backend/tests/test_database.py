import pytest
from app.core.database import AsyncSessionLocal, get_db


@pytest.mark.asyncio
async def test_get_db_yields_session():
    """get_db() must yield an AsyncSession and close it."""
    from sqlalchemy.ext.asyncio import AsyncSession
    gen = get_db()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)
    try:
        await gen.aclose()
    except StopAsyncIteration:
        pass
