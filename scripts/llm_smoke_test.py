import asyncio

from centrag.implementations.bedrock_llm import BedrockLLM
from centrag.implementations.openai_llm import OpenAILLM


async def smoke_test_openai():
    print("\n[SMOKE TEST] OpenAI LLM")
    llm = OpenAILLM(model="gpt-4o-mini") # Use mini for cheaper test
    try:
        response = await llm.generate(
            prompt="Hello, what is 2+2?",
            context=["Context info: Addition is a basic arithmetic operation."],
            system_prompt="You are a helpful assistant."
        )
        print(f"✓ OpenAI Generate: {response.content[:50]}...")
        print(f"✓ OpenAI Metrics: {response.input_tokens} in, {response.output_tokens} out, {response.latency_ms:.1f}ms")
        
        complexity = await llm.classify_complexity("How does quantum gravity work?")
        print(f"✓ OpenAI Complexity: {complexity}")
        
        print("✓ OpenAI Stream: ", end="", flush=True)
        async for chunk in llm.generate_stream(prompt="Say HI", context=[]):
            print(chunk, end="", flush=True)
        print("\n")
    except Exception as e:
        print(f"✗ OpenAI Failed: {e}")

async def smoke_test_bedrock():
    print("\n[SMOKE TEST] Bedrock LLM")
    # Note: Requires AWS credentials set
    llm = BedrockLLM(model_id="anthropic.claude-3-haiku-20240307-v1:0") # Use haiku for cheaper test
    try:
        response = await llm.generate(
            prompt="Hello, what is 2+2?",
            context=["Context info: Addition is a basic arithmetic operation."],
            system_prompt="You are a helpful assistant."
        )
        print(f"✓ Bedrock Generate: {response.content[:50]}...")
        print(f"✓ Bedrock Metrics: {response.input_tokens} in, {response.output_tokens} out, {response.latency_ms:.1f}ms")
        
        complexity = await llm.classify_complexity("How does quantum gravity work?")
        print(f"✓ Bedrock Complexity: {complexity}")

        print("✓ Bedrock Stream: ", end="", flush=True)
        async for chunk in llm.generate_stream(prompt="Say HI", context=[]):
            print(chunk, end="", flush=True)
        print("\n")
    except Exception as e:
        print(f"✗ Bedrock Failed: {e}")

if __name__ == "__main__":
    asyncio.run(smoke_test_openai())
    # asyncio.run(smoke_test_bedrock()) # Uncomment to test bedrock if credentials are set
