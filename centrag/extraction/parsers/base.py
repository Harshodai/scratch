"""
Parser base — ParserProtocol + auto-discovery registry.

Design Pattern: STRATEGY + REGISTRY
    - Each parser implements ParserProtocol
    - ParserRegistry.get(content_type) returns the right parser
    - New parsers are registered via @register_parser decorator

SOLID: Open/Closed — add new formats by creating a new parser file
       and decorating the class. No changes to existing code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.extractor import (
        ContentType,
        ExtractorProtocol,
    )

logger = get_logger("extraction.parsers")


class ParserRegistry:
    """
    Registry for document parsers.

    Usage:
        registry = ParserRegistry()
        registry.register(PDFParser())
        registry.register(DOCXParser())

        parser = registry.get(ContentType.PDF)
        doc = await parser.extract(file_bytes, ContentType.PDF)
    """

    def __init__(self) -> None:
        self._parsers: dict[ContentType, ExtractorProtocol] = {}

    def register(self, parser: ExtractorProtocol) -> None:
        """Register a parser for its supported content types."""
        for ct in parser.supported_types():
            if ct in self._parsers:
                logger.warning(
                    "parser_overridden",
                    content_type=ct.value,
                    old=type(self._parsers[ct]).__name__,
                    new=type(parser).__name__,
                )
            self._parsers[ct] = parser
            logger.info("parser_registered", content_type=ct.value, parser=type(parser).__name__)

    def get(self, content_type: ContentType) -> ExtractorProtocol:
        """Get registered parser for a content type."""
        if content_type not in self._parsers:
            raise ValueError(
                f"No parser registered for content type: {content_type.value}. "
                f"Available: {[ct.value for ct in self._parsers]}"
            )
        return self._parsers[content_type]

    def supported_types(self) -> list[ContentType]:
        """List all content types with registered parsers."""
        return list(self._parsers.keys())

    @property
    def is_empty(self) -> bool:
        return len(self._parsers) == 0
