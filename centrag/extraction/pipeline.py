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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from centrag.abstractions.chunker import ChunkingConfig, ChunkingStrategy, ChunkResult
from centrag.extraction.chunkers.fixed import FixedChunker
from centrag.extraction.chunkers.proposition import PropositionChunker
from centrag.extraction.chunkers.recursive import RecursiveChunker
from centrag.extraction.chunkers.hierarchical import HierarchicalSplitter
from centrag.extraction.contextualizer import SituatedContextGenerator
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from centrag.abstractions.extractor import ContentType, ExtractedDocument
    from centrag.abstractions.llm import LLMProtocol
    from centrag.extraction.parsers.base import ParserRegistry

logger = get_logger("extraction.pipeline")


@dataclass(frozen=True)
class ExtractionResult:
    """Immutable result of the document processing pipeline.

    The WHY:
        Provides a standardized bundle of metadata, raw text, and
        structured chunks. By being immutable, it ensures that
        downstream consumers (VectorStores, Audit Logs) operate
        on consistent data.
    """

    document: ExtractedDocument
    chunks: list[ChunkResult]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def chunk_count(self) -> int:
        """Returns the total number of segments extracted."""
        return len(self.chunks)

    @property
    def total_tokens(self) -> int:
        """Returns the cumulative token count across all chunks."""
        return sum(c.token_count for c in self.chunks)


class ExtractionPipeline:
    """Orchestrator for the document ingestion lifecycle.

    The WHY:
        Raw files are useless for RAG. This pipeline transforms
        binary blobs into searchable "knowledge units". It coordinates:
        1. Parsing: Converting PDF/DOCX/HTML into text.
        2. Contextualization: Adding document-level context to each chunk.
        3. Chunking: Splitting text into optimized segments.
        4. Enrichment: Adding section headers and metadata.

    Design Patterns:
        - FACADE: Simplifies the complex Parse → Chunk flow.
        - STRATEGY: Selects the right parser/chunker based on file type.
        - CHAIN OF THOUGHT: Optionally uses an LLM to "situatue" chunks
          within the overall document (Anthropic 2024 pattern).
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
            ChunkingStrategy.HIERARCHICAL: HierarchicalSplitter(),
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

        if config.strategy == ChunkingStrategy.HIERARCHICAL:
            # Hierarchical splitter has a specific split method signature
            # We cast to any to handle the protocol variation for now
            hier_splitter: HierarchicalSplitter = chunker  # type: ignore
            chunks = hier_splitter.split(
                text=document.text,
                doc_id=document.doc_id or "",
                document_title=document.title or filename,
            )
        else:
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
            contextualizer = SituatedContextGenerator(self._llm_factory())
            chunks = await contextualizer.contextualize(document, chunks)

        # --- Phase 4 pattern: Multivector Enrichment ---
        from centrag.config import get_settings
        settings = get_settings()
        
        if settings.enable_multivector_extraction and self._llm_factory:
            from centrag.extraction.multivector import MultivectorEnricher
            enricher = MultivectorEnricher(self._llm_factory())
            chunks = await enricher.enrich(chunks)
            logger.info("multivector_enrichment_completed", count=len(chunks))

        # --- Phase 4 pattern: Graph Extraction ---
        triplets = []
        if settings.enable_graph_extraction and self._llm_factory:
            from centrag.extraction.graph_extractor import GraphExtractor
            extractor = GraphExtractor(self._llm_factory())
            # For efficiency, we extract from the whole document text or a rolling window
            # Here we extract from the full text to capture global relations
            triplets = await extractor.extract(document.text, document.title or filename)
            logger.info("graph_extraction_completed", triplet_count=len(triplets))

        # --- NEW: Advanced Metadata Extraction (Content-Aware) ---
        global_metadata = {}
        if self._llm_factory:
            from centrag.extraction.metadata_extractor import DocumentMetadataExtractor
            meta_extractor = DocumentMetadataExtractor(self._llm_factory())
            global_metadata = await meta_extractor.extract_metadata(document.text)
            logger.info("global_metadata_extracted", metadata=global_metadata)
            
            # Propagate to all chunks for filtering
            for chunk in chunks:
                chunk.metadata.update(global_metadata)

        return ExtractionResult(
            document=document,
            chunks=chunks,
            metadata={
                "filename": filename,
                "content_type": content_type.value,
                "chunking_strategy": config.strategy.value,
                "chunk_size": config.chunk_size,
                "graph_triplets": [t.__dict__ for t in triplets] if triplets else [], # Temporary storage for ingestion service
                **global_metadata,
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
