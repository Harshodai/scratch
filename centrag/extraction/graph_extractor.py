"""
Graph Extractor — Relational triplet extraction using LLM.

Converts unstructured text into a set of (Subject, Predicate, Object) triplets.
This powers the 'Relational Path' in Phase 4 of CentRAG.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from centrag.abstractions.graph_store import Relation
from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.abstractions.llm import LLMProtocol

logger = get_logger("extraction.graph")


class GraphExtractor:
    """
    LLM-powered knowledge extraction for the Graph RAG path.
    
    The WHY:
        Conventional chunking breaks semantic connections. By extracting 
        explicit triples, we create a 'Knowledge Network' that can be 
        traversed regardless of where the information is physically 
        stored in the document.
        
    Rules:
        1. Only extract essential relations.
        2. Normalize entity names (resolve pronouns).
        3. Output standard JSON format for parsing.
    """

    def __init__(self, llm: LLMProtocol):
        self._llm = llm

    async def extract(self, text: str, document_title: str = "") -> list[Relation]:
        """
        Extract knowledge triplets from a piece of text.
        """
        system_prompt = f"""
        You are a Knowledge Graph Extractor (Triplet Specialist).
        Your task is to extract clear, factual (Subject, Predicate, Object) triplets from the provided text.
        
        Rules:
        1. Resolve all pronouns (it, he, they) to their full names using the context.
        2. Normalize entity names (e.g., "Apple" and "Apple Inc" should both be "Apple Inc").
        3. Extract relations that are useful for answering complex business or technical questions.
        4. Focus on properties, roles, ownership, and causality.
        5. Output ONLY a JSON array of objects with "subject", "predicate", and "object" keys.
        
        Document Title: {document_title}
        """

        prompt = f"Text to extract from:\n{text[:2000]}\n\nJSON Output:"

        try:
            response = await self._llm.generate(
                prompt=prompt, 
                context=[], 
                system_prompt=system_prompt,
                temperature=0.0
            )
            
            import re
            content = response.content.strip()
            # Robust regex-based JSON extraction to handle LLM conversational slop
            # Graph extractor expects an array []
            match = re.search(r"\[.*\]", content, re.DOTALL)
            if not match:
                logger.warning("no_json_array_found_in_response", content=content[:100])
                return []
            
            clean_content = match.group(0)
            data = json.loads(clean_content)
            
            triplets = []
            for item in data:
                if "subject" in item and "predicate" in item and "object" in item:
                    triplets.append(Relation(
                        subject=item["subject"],
                        predicate=item["predicate"],
                        object=item["object"],
                        metadata={"source_doc": document_title}
                    ))
            
            return triplets
        except Exception as e:
            logger.error("graph_extraction_failed", error=str(e), text_sample=text[:100])
            return []
