"""
Hierarchical Chunker — Recursive multi-level document segmentation.

The WHY:
    Standard RAG retrieves flat chunks. Hierarchical retrieval enables
    recursive context expansion: Child (128 tokens) -> Parent (1024 tokens)
    -> Section (Full header block) -> Document (Summary).

    This captures both local precision and global themes.
"""

from __future__ import annotations

import re
import uuid

from centrag.abstractions.chunker import ChunkResult


class HierarchicalSplitter:
    """Implementor of recursive hierarchical splitting logic.

    Transforms structured Markdown into a tree of linked chunks.
    """

    def __init__(self, leaf_size: int = 150, block_size: int = 1000) -> None:
        self._leaf_size = leaf_size
        self._block_size = block_size

    def split(
        self,
        text: str,
        doc_id: str,
        document_title: str = "",
    ) -> list[ChunkResult]:
        """Split text into a hierarchy of chunks.

        Logic:
        1. Identify Sections via Markdown headers.
        2. Create a Section chunk for each major header.
        3. For each section, split content into Blocks.
        4. For each block, split into Leaves.
        """
        all_chunks: list[ChunkResult] = []

        # Step 0: Document Level
        doc_chunk_id = str(uuid.uuid4())
        all_chunks.append(
            ChunkResult(
                content=text[:2000],  # Document summary/intro
                chunk_index=0,
                start_char=0,
                end_char=len(text),
                token_count=len(text) // 4,
                doc_id=doc_id,
                chunk_id=doc_chunk_id,
                level="document",
                breadcrumb_path=document_title or "Root",
            )
        )

        # Step 1: Split by Headers (H1, H2, H3)
        # Regex for Markdown headers
        sections = re.split(r"(^#+\s+.*$)", text, flags=re.MULTILINE)

        current_section_title = document_title
        current_section_id = doc_chunk_id
        char_offset = 0

        # sections list will alternate between empty/text and headers
        for part in sections:
            if not part:
                continue

            is_header = part.startswith("#")
            part_len = len(part)

            if is_header:
                current_section_title = part.strip("# ").strip()
                current_section_id = str(uuid.uuid4())

                all_chunks.append(
                    ChunkResult(
                        content=part,
                        chunk_index=len(all_chunks),
                        start_char=char_offset,
                        end_char=char_offset + part_len,
                        token_count=len(part) // 4,
                        doc_id=doc_id,
                        chunk_id=current_section_id,
                        parent_chunk_id=doc_chunk_id,
                        level="section",
                        breadcrumb_path=f"{document_title} > {current_section_title}",
                    )
                )
            else:
                # Step 2: Split Section Body into Blocks
                blocks = self._simple_split(part, self._block_size)
                for b_idx, block_text in enumerate(blocks):
                    block_id = str(uuid.uuid4())
                    block_start = char_offset + part.find(block_text)
                    block_end = block_start + len(block_text)

                    all_chunks.append(
                        ChunkResult(
                            content=block_text,
                            chunk_index=len(all_chunks),
                            start_char=block_start,
                            end_char=block_end,
                            token_count=len(block_text) // 4,
                            doc_id=doc_id,
                            chunk_id=block_id,
                            parent_chunk_id=current_section_id,
                            level="block",
                            breadcrumb_path=f"{document_title} > {current_section_title} [Block {b_idx}]",
                        )
                    )

                    # Step 3: Split Block into Leaves (High-Precision Chunks)
                    leaves = self._simple_split(block_text, self._leaf_size)
                    for l_idx, leaf_text in enumerate(leaves):
                        leaf_start = block_start + block_text.find(leaf_text)

                        all_chunks.append(
                            ChunkResult(
                                content=leaf_text,
                                chunk_index=len(all_chunks),
                                start_char=leaf_start,
                                end_char=leaf_start + len(leaf_text),
                                token_count=len(leaf_text) // 4,
                                doc_id=doc_id,
                                chunk_id=str(uuid.uuid4()),
                                parent_chunk_id=block_id,
                                level="leaf",
                                breadcrumb_path=f"{document_title} > {current_section_title} > {l_idx}",
                            )
                        )

            char_offset += part_len

        return all_chunks

    def _simple_split(self, text: str, size: int) -> list[str]:
        """Naive splitter by character count for demo purposes."""
        return [text[i : i + size] for i in range(0, len(text), size)]
