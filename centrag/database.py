"""
Database session management.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import Request


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency to get an async database session from the app engine.
    """
    engine = request.app.state.db_engine
    if engine is None:
        raise RuntimeError("PostgreSQL engine is not initialized.")

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session
