"""
Extraction Pipeline — Orchestrates parsing and chunking.

This is the main entry point for document extraction:
  raw file bytes → ExtractionPipeline → list[ChunkResult]

Design Patterns:
  - FACADE: Single entry point hides parser/chunker complexity
  - STRATEGY: Parser and chunker selected at runtime based on content type/config
  - TEMPLATE METHOD: Pipeline flow is fixed (parse → chunk → enrich), steps are swappable

SOLID:
  - SRP: Pipeline only orchestrates. Parsing and chunking are separate.
  - OCP: Add new formats or strategies without modifying this class.
  - DIP: Depends on ParserRegistry and ChunkerProtocol, not concrete classes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from centrag.abstractions.chunker import ChunkingConfig, ChunkingStrategy, ChunkResult
from centrag.abstractions.extractor import ContentType, ExtractedDocument
from centrag.abstractions.llm import LLMProtocol
from centrag.extraction.chunkers.fixed import FixedChunker
from centrag.extraction.chunkers.proposition import PropositionChunker
from centrag.extraction.chunkers.recursive import RecursiveChunker
from centrag.extraction.parsers.base import ParserRegistry
from centrag.utils.logger import get_logger

logger = get_logger("extraction.pipeline")


@dataclass(frozen=True)
class ExtractionResult:
    """Immutable result of the full extraction pipeline."""

    document: ExtractedDocument
    chunks: list[ChunkResult]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

    @property
    def total_tokens(self) -> int:
        return sum(c.token_count for c in self.chunks)


class ExtractionPipeline:
    """
    Orchestrates document extraction and chunking.

    Usage:
        # 1. Create pipeline with registered parsers
        registry = ParserRegistry()
        registry.register(PDFParser())
        registry.register(PlainTextParser())

        pipeline = ExtractionPipeline(
            parser_registry=registry,
            default_chunking=ChunkingConfig(strategy=ChunkingStrategy.RECURSIVE),
        )

        # 2. Process a document
        result = await pipeline.process(
            file_bytes=pdf_bytes,
            content_type=ContentType.PDF,
            filename="report.pdf",
        )

        # 3. Use results
        for chunk in result.chunks:
            embedding = await embedder.embed_query(chunk.content)
            await vectorstore.upsert(...)
    """

    def __init__(
        self,
        parser_registry: ParserRegistry,
        default_chunking: ChunkingConfig | None = None,
        llm_factory: Callable[[], LLMProtocol] | None = None,
    ) -> None:
        self._registry = parser_registry
        self._default_chunking = default_chunking or ChunkingConfig()
        self._llm_factory = llm_factory

        # Pre-built chunker instances (Strategy Pattern)
        self._chunkers = {
            ChunkingStrategy.FIXED: FixedChunker(),
            ChunkingStrategy.RECURSIVE: RecursiveChunker(),
            ChunkingStrategy.PROPOSITION: PropositionChunker(),
            # SEMANTIC and STRUCTURE_AWARE are added when available
        }

        # Try to register optional chunkers
        try:
            from centrag.extraction.chunkers.structure_aware import StructureAwareChunker

            self._chunkers[ChunkingStrategy.STRUCTURE_AWARE] = StructureAwareChunker()
        except ImportError:
            pass

    def register_chunker(self, strategy: ChunkingStrategy, chunker: Any) -> None:
        """Register a custom chunker for a strategy."""
        self._chunkers[strategy] = chunker
        logger.info("chunker_registered", strategy=strategy.value)

    async def process(
        self,
        file_bytes: bytes,
        content_type: ContentType,
        filename: str = "",
        chunking_config: ChunkingConfig | None = None,
    ) -> ExtractionResult:
        """
        Full extraction pipeline: Parse → Chunk → Return.

        Args:
            file_bytes:      Raw file content.
            content_type:    MIME type of the file.
            filename:        Original filename for metadata.
            chunking_config: Override default chunking config.

        Returns:
            ExtractionResult with document metadata and chunks.
        """
        config = chunking_config or self._default_chunking

        # --- Step 1: Parse ---
        parser = self._registry.get(content_type)
        document = await parser.extract(file_bytes, content_type, filename)

        logger.info(
            "document_parsed",
            filename=filename,
            content_type=content_type.value,
            chars=document.char_count,
            tables=document.table_count,
        )

        # --- Step 2: Extract section headers (for context enrichment) ---
        section_headers = [el.content for el in document.elements if el.element_type == "header"]

        # --- Step 3: Chunk ---
        chunker = self._chunkers.get(config.strategy)
        if chunker is None:
            logger.warning(
                "chunker_not_found",
                strategy=config.strategy.value,
                fallback="recursive",
            )
            chunker = self._chunkers[ChunkingStrategy.RECURSIVE]

        chunks = chunker.chunk(
            text=document.text,
            config=config,
            document_title=document.title or filename,
            section_headers=section_headers[:5],  # Limit header depth
        )

        logger.info(
            "document_chunked",
            filename=filename,
            strategy=config.strategy.value,
            chunk_count=len(chunks),
            total_tokens=sum(c.token_count for c in chunks),
        )

        # --- Step 4: Contextualize Chunks (Anthropic 2024 Pattern) ---
        if config.enable_contextual_retrieval and self._llm_factory:
            llm = self._llm_factory()
            logger.info("contextualizing_chunks", chunk_count=len(chunks))

            # Implementation note: In production this would be parallelized
            for chunk in chunks:
                prompt = f"""
                <document>
                {document.text[:10000]}  # Context window limit for summary
                </document>
                
                Here is a chunk from the document:
                <chunk>
                {chunk.content}
                </chunk>
                
                Please provide a short, one-sentence context that situates this chunk within the overall document 
                to improve retrieval. Respond only with the one-sentence context.
                """

                try:
                    llm_resp = await llm.generate(prompt)
                    context_summary = llm_resp.content.strip()
                    # Prepend context to the chunk content
                    new_content = f"[Context: {context_summary}]\n\n{chunk.content}"

                    # Update chunk content (we need to create a new instance if frozen)
                    from dataclasses import replace

                    chunks[chunks.index(chunk)] = replace(chunk, content=new_content)
                except Exception as e:
                    logger.warning("contextualization_failed", error=str(e))
                    continue

        return ExtractionResult(
            document=document,
            chunks=chunks,
            metadata={
                "filename": filename,
                "content_type": content_type.value,
                "chunking_strategy": config.strategy.value,
                "chunk_size": config.chunk_size,
            },
        )

    async def process_batch(
        self,
        files: list[tuple[bytes, ContentType, str]],
        chunking_config: ChunkingConfig | None = None,
    ) -> list[ExtractionResult]:
        """Process multiple files. Sequential for safety; override for parallelism."""
        results = []
        for file_bytes, content_type, filename in files:
            try:
                result = await self.process(file_bytes, content_type, filename, chunking_config)
                results.append(result)
            except Exception as e:
                logger.error("extraction_failed", filename=filename, error=str(e))
                # Continue processing remaining files
                continue
        return results

    @property
    def supported_types(self) -> list[ContentType]:
        """List all content types that can be processed."""
        return self._registry.supported_types()

    @property
    def available_strategies(self) -> list[ChunkingStrategy]:
        """List all registered chunking strategies."""
        return list(self._chunkers.keys())
