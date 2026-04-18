import asyncio
import os
import subprocess
import sys
import time

from mcp import ClientSession
from mcp.client.sse import sse_client

async def test_mcp_link():
    print("Starting Public MCP Link SSE Injection Test...")
    
    # 1. Start the remote Server (our dummy_sse_mcp representing Jira/Confluence on the internet)
    print("Spinning up remote SSE Server on port 8124...")
    server_process = subprocess.Popen(
        [sys.executable, "tests/dummy_sse_mcp.py", "--port", "8124"]
    )
    time.sleep(2)  # Wait for server to boot
    
    try:
        url = "http://127.0.0.1:8124/sse"
        print(f"Simulating User providing Link in UI: {url}")
        
        # 2. Ephemeral Token Injection (Zero Trust - never stored in DB)
        ephemeral_headers = {
            "Authorization": "Bearer JIRA_EPHEMERAL_TOKEN_12345",
            "X-Team-ID": "team-security-test"
        }
        print(f"Injecting Ephemeral Headers into Bridge Layer: {ephemeral_headers}")
        
        # 3. Connect via Bridge architecture logic
        async with sse_client(url, headers=ephemeral_headers) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("Successfully established SSE connection to remote MCP!")
                
                # Fetch tools
                tools = await session.list_tools()
                print(f"Discovered {len(tools.tools)} remote tools.")
                for t in tools.tools:
                    print(f"   - {t.name}: {t.description}")
                
                # Call a tool directly using the ephemeral context
                print("\nExecuting action on remote server...")
                result = await session.call_tool("search_documents", {"query": "security protocols"})
                print(f"Remote Server Response:\n{result.content[0].text}")
                
    except Exception as e:
        print(f"Error during MCP Link testing: {e}")
    finally:
        print("Cleaning up remote server process...")
        server_process.terminate()

if __name__ == "__main__":
    asyncio.run(test_mcp_link())
