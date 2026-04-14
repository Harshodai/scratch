"""
Document Metadata Extractor — LLM-powered extraction of global document attributes.

The WHY:
    Implicit metadata (filename) is often inconsistent or missing. By using an LLM 
    to analyze the document head (first few pages/blocks), we can extract high-fidelity 
    attributes like `post_title`, `post_year`, and `post_month` with near-100% accuracy.
    
    This metadata is then shared across all chunks for precise vector filtering.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.llm import LLMProtocol

logger = get_logger("extraction.metadata")


class DocumentMetadataExtractor:
    """
    Extracts structured metadata from document content using LLM reasoning.
    """

    def __init__(self, llm: LLMProtocol):
        self._llm = llm

    async def extract_metadata(self, text: str) -> dict[str, Any]:
        """
        Analyze document text and extract title, year, month, and other attributes.
        
        Args:
            text: Full text or document prefix.
            
        Returns:
            dict: Structured metadata dictionary.
        """
        # We only need the first 4000 chars to identify title/date usually
        doc_head = text[:4000]
        
        system_prompt = (
            "You are a Document Metadata Specialist. Analyze the provided document intro and extract:\n"
            "1. 'post_title': The clear, semantic title of the document.\n"
            "2. 'post_year': The 4-digit year of publication (as a string).\n"
            "3. 'post_month': The month of publication (full name or number).\n"
            "4. 'author': If identifiable.\n"
            "\n"
            "Output ONLY a JSON object. If a field is missing, use null."
        )
        
        try:
            response = await self._llm.generate(
                prompt=f"Document Intro:\n{doc_head}",
                context=[],
                system_prompt=system_prompt,
                temperature=0.0
            )
            
            import re
            content = response.content.strip()
            # Robust regex-based JSON extraction to handle LLM conversational slop
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                logger.warning("no_json_found_in_response", content=content[:100])
                return {}
            
            clean_content = match.group(0)
            metadata = json.loads(clean_content)
            
            # Filter out nulls
            return {k: v for k, v in metadata.items() if v is not None}
            
        except Exception as e:
            logger.warning("metadata_extraction_failed", error=str(e))
            return {}
