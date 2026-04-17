import pytest
from centrag.config import get_settings
from centrag.wiring import build_retrieval_engine
from centrag.retrieval.engine import RetrievalEngine

def test_mcp_bridge_wiring_sanity():
    """Verify that build_retrieval_engine correctly injects the MCPBridge."""
    settings = get_settings()
    # Force enable MCP for test
    settings.enable_mcp = True
    
    engine = build_retrieval_engine(settings=settings)
    
    assert isinstance(engine, RetrievalEngine)
    assert engine.mcp_bridge is not None
    
    # Check if 'enterprise' is registered via auto-detection
    assert "enterprise" in settings.mcp_external_servers
    assert settings.mcp_external_servers["enterprise"][2] == "mcp_enterprise_server.server"
    
    print("OK: MCPBridge wired and Enterprise server auto-detected")

if __name__ == "__main__":
    test_mcp_bridge_wiring_sanity()
