"""
Situated Context Generator — Implements Anthropic's "Contextual Retrieval" pattern.

The WHY:
By providing chunk-level document context (document summary + section breadcrumbs),
we significantly improve retrieval accuracy for vague or cross-referencing queries.

Goal: "Maximize semantic overlap between query and chunk."
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.chunker import ChunkResult
    from centrag.abstractions.extractor import ExtractedDocument
    from centrag.abstractions.llm import LLMProtocol

logger = get_logger("extraction.contextualizer")


class SituatedContextGenerator:
    """
    Orchestrates the situational context generation for document chunks.
    """

    def __init__(self, llm: LLMProtocol) -> None:
        self._llm = llm

    def _build_context_prompt(self, document_text: str, chunk_content: str) -> str:
        """Construct the prompt for the situational summary."""
        # Use first 8k chars for doc summary to stay within context limits
        doc_guide = document_text[:8000]

        return f"""
        <document>
        {doc_guide}
        </document>
        
        Here is a specific chunk from the document above:
        <chunk>
        {chunk_content}
        </chunk>
        
        Please provide a short, one-sentence context that situates this chunk within the overall document 
        to improve retrieval. This summary should mention the document's main topic and where this 
        specific chunk fits (e.g., section, topic).
        
        Respond only with the one-sentence context summary.
        """

    async def contextualize(self, document: ExtractedDocument, chunks: list[ChunkResult]) -> list[ChunkResult]:
        """
        Enriches a list of chunks with situational context summaries.
        """
        logger.info("contextualizing_chunks_started", count=len(chunks))

        from dataclasses import replace

        # Batching/Concurrency control would be implemented here in production
        # For now, we process as independent tasks
        tasks = []
        for chunk in chunks:
            prompt = self._build_context_prompt(document.text, chunk.content)
            tasks.append(self._llm.generate(prompt))

        try:
            responses = await asyncio.gather(*tasks, return_exceptions=True)

            hardened_chunks = []
            for i, response in enumerate(responses):
                chunk = chunks[i]
                if isinstance(response, Exception):
                    logger.warning("chunk_contextualization_failed", chunk_index=i, error=str(response))
                    hardened_chunks.append(chunk)
                    continue

                context_summary = response.content.strip()
                # Prepend the context to the content as per the Substack recommendation
                enriched_content = f"[Context: {context_summary}]\n\n{chunk.content}"

                # Create a new ChunkResult instance with the enriched content
                hardened_chunks.append(replace(chunk, content=enriched_content))

            logger.info("contextualizing_chunks_completed", count=len(hardened_chunks))
            return hardened_chunks

        except Exception as e:
            logger.error("contextualization_batch_failed", error=str(e))
            return chunks
