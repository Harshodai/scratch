"""
Tests for HybridRetriever — RRF fusion of dual-path results.

Verifies:
    - RRF score calculation
    - Deduplication across paths
    - Provenance tracking (which path contributed)
    - Empty input handling
    - Top-N limiting
"""

from __future__ import annotations

from centrag.retrieval.hybrid import HybridRetriever


def _make_result(doc_id: str, content: str, score: float = 0.9) -> dict:
    return {
        "document_id": doc_id,
        "content": content,
        "relevance_score": score,
        "metadata": {"source": "test"},
    }


class TestRRFFusion:
    """Core RRF score calculation tests."""

    def test_single_path_results(self):
        """Results from one path only should still be ranked."""
        hybrid = HybridRetriever(k=60)
        result = hybrid.fuse(
            pageindex_results=[
                _make_result("d1", "Risk factors are..."),
                _make_result("d2", "Revenue grew by..."),
            ],
            vector_results=[],
            top_n=5,
        )

        assert len(result.fused) == 2
        assert result.fused[0].rrf_score > result.fused[1].rrf_score
        assert result.pageindex_count == 2
        assert result.vector_count == 0

    def test_both_paths_results(self):
        """Results from both paths are fused."""
        hybrid = HybridRetriever(k=60)
        result = hybrid.fuse(
            pageindex_results=[
                _make_result("d1", "Content A"),
                _make_result("d2", "Content B"),
            ],
            vector_results=[
                _make_result("d3", "Content C"),
                _make_result("d4", "Content D"),
            ],
            top_n=10,
        )

        assert len(result.fused) == 4
        assert result.pageindex_count == 2
        assert result.vector_count == 2

    def test_rrf_scores_decrease_with_rank(self):
        """RRF score = 1/(k+rank), so rank 1 > rank 2 > rank 3."""
        hybrid = HybridRetriever(k=60)
        result = hybrid.fuse(
            pageindex_results=[
                _make_result("d1", "First"),
                _make_result("d2", "Second"),
                _make_result("d3", "Third"),
            ],
            vector_results=[],
        )

        scores = [r.rrf_score for r in result.fused]
        assert scores == sorted(scores, reverse=True)

    def test_rrf_score_formula(self):
        """Verify the exact RRF score for rank 1 with k=60."""
        hybrid = HybridRetriever(k=60)
        result = hybrid.fuse(
            pageindex_results=[_make_result("d1", "Only result")],
            vector_results=[],
        )

        expected = 1.0 / (60 + 1)  # rank=1, k=60
        assert abs(result.fused[0].rrf_score - expected) < 1e-10


class TestDeduplication:
    """Results appearing in both paths should be merged."""

    def test_duplicate_boosted(self):
        """Same content from both paths gets higher combined score."""
        hybrid = HybridRetriever(k=60)

        # Same doc_id and content in both paths
        shared = _make_result("d1", "Shared content from both paths")

        result = hybrid.fuse(
            pageindex_results=[shared],
            vector_results=[shared],
        )

        # Should be 1 result (deduplicated) with boosted score
        assert len(result.fused) == 1
        # Score should be sum of both: 1/(60+1) + 1/(60+1)
        expected = 2.0 / (60 + 1)
        assert abs(result.fused[0].rrf_score - expected) < 1e-10

    def test_different_content_not_merged(self):
        """Different content from same doc_id are separate."""
        hybrid = HybridRetriever(k=60)

        result = hybrid.fuse(
            pageindex_results=[_make_result("d1", "Content A from pageindex")],
            vector_results=[_make_result("d1", "Content B from vector")],
        )

        # Different content → not merged
        assert len(result.fused) == 2


class TestProvenance:
    """Track which path(s) contributed each result."""

    def test_single_source_tracking(self):
        """Result from one path shows that source."""
        hybrid = HybridRetriever(k=60)
        result = hybrid.fuse(
            pageindex_results=[_make_result("d1", "PI only")],
            vector_results=[_make_result("d2", "Vec only")],
        )

        pi_result = next(r for r in result.fused if r.document_id == "d1")
        vec_result = next(r for r in result.fused if r.document_id == "d2")

        assert "pageindex" in pi_result.sources
        assert "vector" in vec_result.sources

    def test_dual_source_tracking(self):
        """Result from both paths shows both sources."""
        hybrid = HybridRetriever(k=60)
        shared = _make_result("d1", "Shared")

        result = hybrid.fuse(
            pageindex_results=[shared],
            vector_results=[shared],
        )

        assert len(result.fused) == 1
        assert set(result.fused[0].sources) == {"pageindex", "vector"}


class TestEdgeCases:
    """Edge case handling."""

    def test_empty_inputs(self):
        """No results from either path."""
        hybrid = HybridRetriever(k=60)
        result = hybrid.fuse([], [])
        assert len(result.fused) == 0
        assert result.pageindex_count == 0
        assert result.vector_count == 0

    def test_top_n_limits(self):
        """top_n limits the number of fused results."""
        hybrid = HybridRetriever(k=60)
        results = [_make_result(f"d{i}", f"Content {i}") for i in range(20)]

        result = hybrid.fuse(
            pageindex_results=results[:10],
            vector_results=results[10:],
            top_n=5,
        )

        assert len(result.fused) == 5

    def test_custom_k_parameter(self):
        """Different k values change relative scoring."""
        hybrid_low = HybridRetriever(k=1)
        hybrid_high = HybridRetriever(k=100)

        results = [_make_result("d1", "Content")]

        low_result = hybrid_low.fuse(results, [])
        high_result = hybrid_high.fuse(results, [])

        # Lower k → higher score for rank 1
        assert low_result.fused[0].rrf_score > high_result.fused[0].rrf_score

    def test_metadata_preserved(self):
        """Result metadata flows through fusion."""
        hybrid = HybridRetriever(k=60)
        result = hybrid.fuse(
            pageindex_results=[
                {
                    "document_id": "d1",
                    "content": "text",
                    "relevance_score": 0.95,
                    "metadata": {"page_refs": "5-7", "section": "Risk"},
                }
            ],
            vector_results=[],
        )

        assert result.fused[0].metadata["page_refs"] == "5-7"
        assert result.fused[0].relevance_score == 0.95
