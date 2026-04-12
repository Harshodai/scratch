import asyncio

from centrag.extraction.chunkers.proposition import PropositionChunker
from centrag.implementations.noop_llm import NoOpLLM


async def smoke_test():
    llm = NoOpLLM()
    chunker = PropositionChunker(llm=llm)

    sample_text = (
        "CentRAG is a multi-tenant RAG platform. It is built with FastAPI. The system uses Qdrant for vector storage."
    )

    print(f"Testing PropositionChunker with text: '{sample_text}'")
    chunks = await chunker.chunk(sample_text)

    print("\nResulting Chunks:")
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i + 1}: {chunk.content}")

    if len(chunks) > 0:
        print("\nWiring successful! Chunks generated.")
    else:
        print("\nWiring failed! No chunks generated.")


if __name__ == "__main__":
    asyncio.run(smoke_test())
