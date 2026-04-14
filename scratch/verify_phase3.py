import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from centrag.config import get_settings
from centrag.wiring import build_ingestion_service, build_retrieval_engine
from centrag.abstractions.retrieval import RetrievalRequest
from centrag.middleware import RequestContext
from centrag.abstractions.extractor import ContentType

async def verify_phase3():
    print("STARTING: Phase 3 Verification...")
    
    # Check dependencies
    try:
        import qdrant_client
    except ImportError:
        print("ERROR: qdrant-client not installed. Please run: pip install qdrant-client")
        return

    # 1. Configure settings for Phase 3
    settings = get_settings()
    settings.enable_hierarchical_retrieval = True
    settings.enable_late_chunking = True
    settings.llm_provider = "noop"
    settings.embedder_provider = "noop"
    settings.enable_vector = True
    # Use local qdrant if possible, otherwise noop vectorstore will be wired by build_components
    settings.qdrant_local_path = "data/qdrant_verify"
    settings.data_dir = "data/verify_docs"

    # 2. Build services
    ingestion = build_ingestion_service(settings)
    engine = build_retrieval_engine(settings)

    team_id = "verify-team"
    doc_id = "phase3-test-doc"
    
    # 3. Create a hierarchical document
    content = """# Section 1: Overview
This is the overview paragraph. It is a block.
This is another sentence in the same block.

## Subsection 1.1: Detail
This is a detailed leaf node. It contains specific technical information.
The target keyword is 'PLATYPUS'.
"""
    
    print("\nINGESTING: Hierarchical document...")
    result = await ingestion.ingest(
        file_bytes=content.encode("utf-8"),
        filename="test.md",
        team_id=team_id,
        content_type="text/markdown",
        namespace="verify"
    )
    
    print(f"SUCCESS: Ingestion complete. Doc ID: {result.doc_id}")
    print(f"STATS: Chunks={result.chunk_count}, Status={result.status}")
    if result.error:
        print(f"ERROR: {result.error}")

    # 4. Retrieval
    print("\nQUERYING: For 'PLATYPUS'...")
    request = RetrievalRequest(
        query="What is the detailed information about PLATYPUS?",
        namespace="verify",
        max_results=3,
        mode="vector"
    )
    ctx = RequestContext(
        team_id=team_id, 
        team_name="VerifyTeam", 
        api_key_id="sk-verify",
        request_id="v-1"
    )
    
    response = await engine.retrieve(request, ctx)
    
    print(f"\nRESPONSE: {response.answer}")
    print(f"SOURCES: Retrieved {len(response.sources)}")
    
    for i, source in enumerate(response.sources):
        expansion = source.metadata.get("expansion_depth", 0)
        print(f"--- Source {i+1} (Relevance: {source.relevance_score:.2f}, Expansion: {expansion}) ---")
        print(f"Content snippet: {source.content[:150]}...")
        
        if "[Context Expanded]" in source.content:
            print("SUCCESS: Hierarchical expansion detected!")

    # 5. Summary
    if any("[Context Expanded]" in s.content for s in response.sources):
        print("\nVERIFIED: Multi-level hierarchical retrieval and context expansion are working.")
    else:
        print("\nFAILED: Context expansion not detected in sources.")

if __name__ == "__main__":
    asyncio.run(verify_phase3())
