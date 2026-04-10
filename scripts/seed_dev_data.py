import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from centrag.models import Base

async def init_models(db_url: str) -> None:
    """
    Initialize all database tables in the connected PostgreSQL instance.
    This creates the models directly via SQLAlchemy metadata. Real deployments
    should favor Alembic migrations for data resiliency.
    """
    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        print("Creating all tables in Dev PostgreSQL...")
        await conn.run_sync(Base.metadata.create_all)
        print("Done. Seed operations complete.")

if __name__ == "__main__":
    db_string = os.getenv("CENTRAG_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/centrag")
    asyncio.run(init_models(db_string))
