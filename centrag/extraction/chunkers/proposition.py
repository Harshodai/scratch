"""
Proposition Chunker — Decomposes text into atomic, standalone propositions.

Based on "RAG Made Simple" (Ch 4) and Chen et al. (2023).
This involves:
1. Sentence splitting (Context-aware).
2. Standalone resolution (Pronoun resolution + Entity clarification).
3. Redundancy removal.

This is a Proof-of-Concept (PoC) implementation.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from centrag.abstractions.chunker import (
    ChunkerProtocol,
    ChunkingConfig,
    ChunkingStrategy,
    ChunkResult,
)
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.llm import LLMProtocol

logger = get_logger("extraction.chunkers.proposition")


class PropositionChunker(ChunkerProtocol):
    """
    Decomposes text into atomic, independent propositions.

    A proposition is a standalone statement that can be understood
    without the surrounding context.

    Example:
    Original: "He founded the company in 2024. It was successful."
    Propositions:
    - "John Doe founded Example Corp in 2024."
    - "Example Corp was successful."
    """

    def __init__(self, llm: LLMProtocol | None = None) -> None:
        self._llm = llm

    @property
    def strategy(self) -> ChunkingStrategy:
        return ChunkingStrategy.PROPOSITION  # Needs addition to Enum in reality

    async def chunk(
        self,
        text: str,
        config: ChunkingConfig | None = None,
        document_title: str = "",
        section_headers: list[str] | None = None,
    ) -> list[ChunkResult]:
        """
        Extract propositions from the text.

        PoC Algorithm:
        1. Split into sentences using a refined regex.
        2. If LLM is available, use it to 'standalone-ify' the sentences.
        3. Otherwise, use a 'Context Enrichment' heuristic.
        """
        config = config or ChunkingConfig(strategy=ChunkingStrategy.RECURSIVE)  # Fallback

        # 1. Simple sentence splitting (PoC heuristic)
        # In production, use spacy or nltk
        sentences = re.split(r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?)\s", text)

        results: list[ChunkResult] = []
        current_pos = 0

        for idx, sentence in enumerate(sentences):
            # 2. Standalone Resolution
            proposition = sentence.strip()

            if self._llm:
                try:
                    proposition = await self._standalone_ify(
                        sentence=proposition, context=text, title=document_title, headers=section_headers or []
                    )
                except Exception as e:
                    logger.warning("llm_proposition_extraction_failed", error=str(e))
                    # Fallback to context enrichment
                    proposition = self._enrich_with_context(proposition, document_title, section_headers)
            else:
                proposition = self._enrich_with_context(proposition, document_title, section_headers)

            # Calculate offsets
            pos = text.find(sentence, current_pos)
            start_char = pos if pos >= 0 else current_pos
            end_char = start_char + len(sentence)

            results.append(
                ChunkResult(
                    content=proposition,
                    chunk_index=idx,
                    start_char=start_char,
                    end_char=end_char,
                    token_count=int(len(proposition.split()) * 1.3),
                    metadata={
                        "strategy": "proposition",
                        "original_sentence": sentence,
                        "document_title": document_title,
                    },
                )
            )
            current_pos = end_char

        return results

    async def _standalone_ify(self, sentence: str, context: str, title: str, headers: list[str]) -> str:
        """Use LLM to resolve pronouns and entities into a standalone proposition."""
        if not self._llm:
            return sentence

        system_prompt = (
            "You are a Proposition Extractor. Convert the given sentence into a standalone proposition.\n"
            "Rules:\n"
            "1. Resolve pronouns (he, it, they) using the provided context.\n"
            "2. Include essential entities (companies, people) instead of references.\n"
            "3. Keep it atomic and factual.\n"
            "4. Output ONLY the standalone sentence."
        )

        prompt = (
            f"Document Title: {title}\n"
            f"Context: {headers[-1] if headers else 'General'}\n"
            f"Sentence to transform: {sentence}\n"
            f"Surrounding Snippet: {context[:500]}..."  # Simple window for PoC
        )

        response = await self._llm.generate(
            prompt=prompt, context=[], system_prompt=system_prompt, temperature=0.0, max_tokens=200
        )
        return response.content.strip()

    def _enrich_with_context(self, sentence: str, title: str, headers: list[str] | None) -> str:
        """Heuristic fallback: Prepend breadcrumbs context."""
        context_str = f"[{title}]" if title else ""
        if headers:
            context_str += f"({' > '.join(headers)})"

        return f"{context_str} {sentence}" if context_str else sentence

    def chunk_boundaries(
        self,
        text: str,
        config: ChunkingConfig | None = None,
    ) -> list[tuple[int, int]]:
        # This implementation requires async but protocol is sync?
        # Actually, ChunkerProtocol in CentRAG has both patterns.
        # For the PoC, we'll keep it simple.
        return []  # Needs matching implementation in production
