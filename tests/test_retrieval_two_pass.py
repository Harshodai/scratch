"""
Tests for Two-Pass Generation and Hierarchical Grounding.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from centrag.abstractions.llm import LLMResponse
from centrag.abstractions.retrieval import SourceChunk
from centrag.retrieval.generator import TwoPassGenerator


@pytest.mark.asyncio
async def test_two_pass_generator_flow():
    """
    Verify that TwoPassGenerator calls LLM multiple times:
    - Once per chunk for fact extraction (Pass 1)
    - Once for final synthesis (Pass 2)
    """
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(
        side_effect=[
            LLMResponse(
                content="Fact 1", model="mock", input_tokens=10, output_tokens=5, latency_ms=100
            ),  # Chunk 1 Facts
            LLMResponse(
                content="Fact 2", model="mock", input_tokens=10, output_tokens=5, latency_ms=100
            ),  # Chunk 2 Facts
            LLMResponse(
                content="Final Answer", model="mock", input_tokens=50, output_tokens=20, latency_ms=200
            ),  # Synthesis
        ]
    )

    generator = TwoPassGenerator(llm=mock_llm)

    sources = [
        SourceChunk(content="content 1", document_id="doc1", chunk_index=1, relevance_score=0.9),
        SourceChunk(content="content 2", document_id="doc1", chunk_index=2, relevance_score=0.8),
    ]

    response = await generator.generate_response(query="What is X?", sources=sources, team_id="team_1")

    assert response.content == "Final Answer"
    # 2 chunk extractions + 1 synthesis = 3 calls
    assert mock_llm.generate.call_count == 3


@pytest.mark.asyncio
async def test_two_pass_generator_caching():
    """
    Verify that fact extraction is cached, reducing LLM calls on second pass.
    """
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(
        return_value=LLMResponse(content="Cached Fact", model="mock", input_tokens=10, output_tokens=5, latency_ms=100)
    )

    mock_cache = MagicMock()
    # First call: miss. Second call: hit.
    mock_cache.get = AsyncMock(
        side_effect=[
            MagicMock(hit=False),  # Call 1: Miss
            MagicMock(hit=True, value="Cached Fact"),  # Call 2: Hit
        ]
    )
    mock_cache.set = AsyncMock()

    generator = TwoPassGenerator(llm=mock_llm, cache=mock_cache)

    source = [SourceChunk(content="some content", document_id="doc1", chunk_index=1, relevance_score=0.9)]

    # 1. First execution (Miss)
    await generator.generate_response(query="test query", sources=source)
    assert mock_llm.generate.call_count == 2  # 1 extraction + 1 synthesis
    assert mock_cache.set.call_count == 1

    mock_llm.generate.reset_mock()

    # 2. Second execution (Hit)
    await generator.generate_response(query="test query", sources=source)
    # Only synthesis should be called (1 call), extraction is cached
    assert mock_llm.generate.call_count == 1
    assert "You are a technical assistant." in mock_llm.generate.call_args[1]["prompt"]
