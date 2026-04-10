import asyncio
import os
import secrets
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from centrag.models import Team, ApiKey

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("create_test_team")

async def create_team(db_url: str, team_name: str) -> None:
    """
    Onboarding script to bootstrap a Dev/Test Team along with their default API Key.
    """
    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    
    async with async_session() as session:
        # Create team instance
        team = Team(name=team_name, tier="enterprise")
        session.add(team)
        await session.flush()  # Extract the newly minted UUID
        
        # In a real environment, the raw_key should be generated and hashed through auth modules.
        # This acts as a naive prototype for sandbox onboarding.
        raw_key = secrets.token_urlsafe(32)
        key_hash = raw_key[::-1] # Dummy predictable fast-hash for local test matching
        
        api_key = ApiKey(
            team_id=team.id,
            name="dev-sandbox-key",
            key_hash=key_hash
        )
        session.add(api_key)
        await session.commit()
        
        logger.info(f"Successfully Created Sandbox Team: {team.name}")
        logger.info(f"Team ID (Namespace): {team.id}")
        logger.info(f"Auth Token (Keep Secret): {raw_key}")
        logger.info(f"Internal Key Hash: {key_hash}")

if __name__ == "__main__":
    db_string = os.getenv("CENTRAG_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/centrag")
    asyncio.run(create_team(db_string, "Development Sandbox Team"))
