import pytest
from unittest.mock import AsyncMock, MagicMock
from centrag.cache.semantic import SemanticCache
from centrag.abstractions.cache import CacheResult, CacheTier

@pytest.mark.asyncio
async def test_semantic_cache_hit():
    """Verify that semantic cache returns a hit when score > threshold."""
    # Mock dependencies
    mock_vs = AsyncMock()
    mock_scalar = AsyncMock()
    mock_emb = AsyncMock()
    
    # 1. Setup mock search result with high similarity (0.98 > 0.95)
    match = MagicMock()
    match.score = 0.98
    match.payload = {"scalar_key": "original query"}
    mock_vs.search.return_value = [match]
    
    # 2. Setup mock embedder
    mock_emb.embed_query.return_value = [0.1] * 1024
    
    # 3. Setup mock scalar store (L2 Redis)
    mock_scalar.get.return_value = CacheResult(
        hit=True, 
        tier=CacheTier.L2_EXACT, 
        value="Calculated Answer"
    )
    
    cache = SemanticCache(
        vector_store=mock_vs,
        scalar_store=mock_scalar,
        embedder=mock_emb,
        similarity_threshold=0.95
    )
    
    result = await cache.get("rephrased query", team_id="team1")
    
    assert result.hit is True
    assert result.tier == CacheTier.L3_SEMANTIC
    assert result.value == "Calculated Answer"
    
    # Verify search was called with team_id filter
    mock_vs.search.assert_called_once()
    filter_arg = mock_vs.search.call_args.kwargs["filter"]
    assert any(m["match"]["value"] == "team1" for m in filter_arg.must)


@pytest.mark.asyncio
async def test_semantic_cache_miss_low_score():
    """Verify that semantic cache returns a miss when score < threshold."""
    mock_vs = AsyncMock()
    mock_scalar = AsyncMock()
    mock_emb = AsyncMock()
    
    # Score 0.8 < 0.95 threshold
    match = MagicMock()
    match.score = 0.8
    match.payload = {"scalar_key": "some key"}
    mock_vs.search.return_value = [match]
    
    mock_emb.embed_query.return_value = [0.1] * 1024
    
    cache = SemanticCache(
        vector_store=mock_vs,
        scalar_store=mock_scalar,
        embedder=mock_emb,
        similarity_threshold=0.95
    )
    
    result = await cache.get("rephrased query", team_id="team1")
    
    assert result.hit is False
    assert result.tier == CacheTier.MISS


@pytest.mark.asyncio
async def test_semantic_cache_set():
    """Verify that semantic cache stores both scalar and vector data."""
    mock_vs = AsyncMock()
    mock_scalar = AsyncMock()
    mock_emb = AsyncMock()
    
    mock_emb.embed_query.return_value = [0.1] * 1024
    
    cache = SemanticCache(
        vector_store=mock_vs,
        scalar_store=mock_scalar,
        embedder=mock_emb
    )
    
    await cache.set("prompt", "response", team_id="team1")
    
    # Verify scalar write
    mock_scalar.set.assert_called_once_with(
        key="prompt",
        value="response",
        team_id="team1",
        ttl_seconds=3600,
        namespace=None
    )
    
    # Verify vector write
    mock_vs.upsert.assert_called_once()
    upsert_kwargs = mock_vs.upsert.call_args.kwargs
    assert upsert_kwargs["payload"]["scalar_key"] == "prompt"
    assert upsert_kwargs["payload"]["team_id"] == "team1"
