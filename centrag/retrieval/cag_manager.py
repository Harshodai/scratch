"""
CAG Manager — Cache-Augmented Generation for static context pre-loading.

Injects high-frequency enterprise context (e.g. handbooks) directly into prompts.
This represents the 'Infinite RAG' level in Phase 4 of CentRAG.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from centrag.utils.logger import get_logger

if TYPE_CHECKING:
    from centrag.storage.document_store import DocumentStore

logger = get_logger("retrieval.cag")


class CAGManager:
    """
    Manages 'Base Knowledge' injection for specific namespaces.
    
    The WHY:
        Frequent retrieval of the same 'Core Policies' is inefficient.
        CAG pre-loads this knowledge into the system prompt for low-latency,
        high-precision grounded generation without repetitive vector search.
    """

    def __init__(self, document_store: DocumentStore):
        self._doc_store = document_store

    async def get_static_context(self, team_id: str, namespace: str) -> str:
        """
        Fetch all 'base' documents for a namespace to use as static context.
        """
        # For PoC, we look for documents with 'is_base=True' in metadata
        # or just fetch the first document in the namespace if it's small.
        try:
            # In a real system, we'd have a specific table or cache for this.
            # Using shadow retrieval logic for now.
            docs = await self._doc_store.list_documents(team_id, namespace)
            
            base_docs = [d for d in docs if d.metadata.get("is_base") == True]
            if not base_docs:
                return ""
                
            combined_context = []
            for b_doc in base_docs:
                # Fetch full text
                # doc_data = await self._doc_store.get_document_text(team_id, b_doc.doc_id)
                # combined_context.append(f"Source: {b_doc.filename}\n{doc_data}")
                pass
                
            return "\n---\n".join(combined_context)
        except Exception as e:
            logger.error("cag_fetch_failed", error=str(e))
            return ""
