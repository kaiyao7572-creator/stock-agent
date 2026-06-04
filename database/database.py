"""
Async SQLAlchemy engine.
Works with SQLite (aiosqlite) and PostgreSQL (asyncpg) via DATABASE_URL.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_settings
from database.models import Base

settings = get_settings()

# check_same_thread is SQLite-specific; harmless on Postgres
_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_async_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=settings.environment == "development",
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def init_db() -> None:
    """Create all tables (idempotent)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
