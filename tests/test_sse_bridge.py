import asyncio
import sys

from centrag.mcp.bridge import MCPBridge


async def main():
    bridge = MCPBridge()
    
    print("\n[1] Attempting Zero-Trust connection (Header Injection)...")
    success = await bridge.register_external_mcp_sse(
        name="dummy_jira",
        url="http://127.0.0.1:8123/sse",
        # This token is EPHEMERAL and doesn't get saved anywhere in CentRAG config!
        headers={"Authorization": "Bearer test-ephemeral-123"}
    )
    
    if success:
        print("[2] Successfully bridged to external Server using stateless header!")
        print("[3] Attempting to dynamically discover tools...")
        tools = bridge.list_tools()
        print(f"    Available Tools Extracted: {list(tools.keys())}")
        
        print("\n[4] Attempting to execute remote tool (get_jira_status)...")
        try:
            result = await bridge.call_tool("dummy_jira.get_jira_status", {})
            print(f"\n[RESULT]: {result}\n")
        except Exception as e:
            print(f"\n[EXECUTION FAILED]: {e}\n")
    else:
        print("[ERROR] Failed to bridge to external server. Ephemeral connection dropped!")

    await bridge.shutdown()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
