import pytest

from centrag.abstractions.chunker import ChunkingConfig
from centrag.abstractions.extractor import ContentType
from centrag.extraction.parsers.base import ParserRegistry
from centrag.extraction.pipeline import ExtractionPipeline
from centrag.implementations.bm25_sparse_embedder import BM25SparseEmbedder
from centrag.implementations.noop_llm import NoOpLLM
from centrag.retrieval.engine import RetrievalEngine


class TestRAGEnhancements:
    @pytest.mark.asyncio
    async def test_bm25_i18n_stop_words(self):
        # Test English stop word filtering
        embedder = BM25SparseEmbedder()
        text_en = "This is a test sentence with some stop words like the and a."
        vec_en = await embedder.embed_sparse(text_en)

        # Check that common English stop words are NOT in the vector
        # Using the deterministic hash logic from the embedder
        the_hash = embedder._deterministic_hash("the")
        and_hash = embedder._deterministic_hash("and")
        test_hash = embedder._deterministic_hash("test")

        assert the_hash not in vec_en
        assert and_hash not in vec_en
        assert test_hash in vec_en

        # Test French stop word filtering
        text_fr = "Ceci est une phrase de test avec des mots vides comme le et la."
        vec_fr = await embedder.embed_sparse(text_fr)

        le_hash = embedder._deterministic_hash("le")
        la_hash = embedder._deterministic_hash("la")
        test_fr_hash = embedder._deterministic_hash("test")

        assert le_hash not in vec_fr
        assert la_hash not in vec_fr
        assert test_fr_hash in vec_fr

    @pytest.mark.asyncio
    async def test_contextual_retrieval_ingestion(self):
        # Setup pipeline with LLM
        registry = ParserRegistry()
        from centrag.extraction.parsers.text import PlainTextParser

        registry.register(PlainTextParser())

        def llm_factory():
            return NoOpLLM(model_name="test-llm")

        pipeline = ExtractionPipeline(
            parser_registry=registry,
            default_chunking=ChunkingConfig(enable_contextual_retrieval=True),
            llm_factory=llm_factory,
        )

        file_content = b"This is a long document about CentRAG. It is an enterprise RAG platform."
        # Pass the correct ContentType enum
        doc = await pipeline.process(file_content, ContentType.PLAIN_TEXT)

        # Check if summaries were prepended
        for chunk in doc.chunks:
            # NoOpLLM returns "Based on the provided sources..." when context is provided
            assert "Based on the provided sources" in chunk.content
            assert "CentRAG" in chunk.content

    @pytest.mark.asyncio
    async def test_contextual_compression_retrieval(self):
        # Setup engine with NoOpLLM
        def llm_factory():
            return NoOpLLM()

        # The engine uses get_settings().enable_contextual_compression
        # For testing, we can manually enable it by mocking settings if needed,
        # but here we'll just test the _compress_context method directly.
        engine = RetrievalEngine(
            embedder_factory=lambda: None,
            vectorstore_factory=lambda: None,
            reranker_factory=lambda: None,
            llm_factory=llm_factory,
            cache=None,
            memory=None,
        )

        from centrag.abstractions.retrieval import SourceChunk

        # Mock chunks
        chunks = [
            SourceChunk(
                content="Chunk 1 content is here.", document_id="doc1", chunk_index=0, relevance_score=0.9, metadata={}
            ),
            SourceChunk(
                content="Chunk 2 content is also here.",
                document_id="doc1",
                chunk_index=1,
                relevance_score=0.8,
                metadata={},
            ),
        ]

        compressed_chunks = await engine._compress_context("What is Chunk 1?", chunks)

        assert len(compressed_chunks) == 2
        for chunk in compressed_chunks:
            assert "Based on the provided sources" in chunk.content
