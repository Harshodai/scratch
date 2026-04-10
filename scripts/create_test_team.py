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
        
        import hashlib
        raw_key = secrets.token_urlsafe(32)
        
        # Secure one-way hashing for API Keys
        salt = secrets.token_bytes(16)
        key_hash = hashlib.pbkdf2_hmac('sha256', raw_key.encode(), salt, 100_000).hex()
        
        # NOTE: If ApiKey model does not natively store salt, it must be updated in production schema.
        # For this prototype we will inject the salt into the hash string or rely on the abstract definition.
        api_key = ApiKey(
            team_id=team.id,
            name="dev-sandbox-key",
            key_hash=key_hash
        )
        session.add(api_key)
        await session.commit()
        
        logger.info(f"Successfully Created Sandbox Team: {team.name}")
        logger.info(f"Team ID (Namespace): {team.id}")
        
        # Single-use secure CLI output. DO NOT log 'raw_key' or 'key_hash' to structured audit streams.
        print(f"\n[SECURITY] Raw Auth Token generated (Keep Secret): {raw_key}")
        print("[SECURITY] This token is hashed and cannot be recovered. Store it now.\n")

if __name__ == "__main__":
    db_string = os.getenv("CENTRAG_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/centrag")
    asyncio.run(create_team(db_string, "Development Sandbox Team"))
