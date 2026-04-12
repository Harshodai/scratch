import asyncio
import hashlib
import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from centrag.models import ApiKey, Base, Chunk, Document, Team

# Fixed Dev Constants
DEMO_TEAM_NAME = "CentRAG Demo Team"
DEMO_API_KEY = "centrag_dev_token_12345"  # Fixed for local dev testing
DEMO_SALT = b"\x00" * 16  # Fixed salt for deterministic dev hash


async def seed_data(db_url: str) -> None:
    """
    Initialize database schema and populate with demo data for end-to-end testing.
    """
    engine = create_async_engine(db_url, echo=False)

    # 1. Initialize Tables
    async with engine.begin() as conn:
        print("Initializing tables...")
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        # 2. Check for existing Demo Team
        result = await session.execute(select(Team).where(Team.name == DEMO_TEAM_NAME))
        team = result.scalar_one_or_none()

        if not team:
            print(f"Creating Demo Team: {DEMO_TEAM_NAME}")
            team = Team(name=DEMO_TEAM_NAME, tier="enterprise")
            session.add(team)
            await session.flush()

            # 3. Create Demo API Key
            hash_bytes = hashlib.pbkdf2_hmac("sha256", DEMO_API_KEY.encode(), DEMO_SALT, 100_000)
            key_hash = f"{DEMO_SALT.hex()}:{hash_bytes.hex()}"
            api_key = ApiKey(team_id=team.id, name="demo-key-1", key_hash=key_hash)
            session.add(api_key)
            await session.flush()
        else:
            print(f"Demo Team already exists (ID: {team.id})")

        # 4. Add Sample Document
        existing_doc = await session.execute(select(Document).where(Document.team_id == team.id))
        if not existing_doc.first():
            print("Adding sample document and chunks...")
            doc = Document(
                team_id=team.id,
                filename="system_overview.md",
                s3_key="s3://centrag-demo/system_overview.md",
                content_type="text/markdown",
                size_bytes=1024,
                status="ready",
            )
            session.add(doc)
            await session.flush()

            chunks = [
                Chunk(
                    document_id=doc.id,
                    team_id=team.id,
                    chunk_index=0,
                    content="CentRAG is an enterprise-grade RAG platform using a dual-path retrieval strategy. It combines Vector search with a PageIndex tree-based retrieval.",
                    token_count=25,
                    vector_id=f"vec-{uuid.uuid4()}",
                ),
                Chunk(
                    document_id=doc.id,
                    team_id=team.id,
                    chunk_index=1,
                    content="The hybrid retriever uses Reciprocal Rank Fusion (RRF) with k=60 to merge results from different paths. This ensures high precision and robust recall.",
                    token_count=28,
                    vector_id=f"vec-{uuid.uuid4()}",
                ),
            ]
            session.add_all(chunks)
            doc.chunk_count = len(chunks)
            await session.commit()
            print(f"Seed complete. Team ID: {team.id}")
            print(f"Dev API Key: {DEMO_API_KEY}")
        else:
            print("Demo data already seeded.")


if __name__ == "__main__":
    db_string = os.getenv("CENTRAG_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/centrag")
    asyncio.run(seed_data(db_string))
