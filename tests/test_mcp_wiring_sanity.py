from centrag.config import get_settings
from centrag.retrieval.engine import RetrievalEngine
from centrag.wiring import build_retrieval_engine


def test_mcp_bridge_wiring_sanity():
    """Verify that build_retrieval_engine correctly injects the MCPBridge."""
    settings = get_settings()
    # Force enable MCP for test
    settings.enable_mcp = True

    engine = build_retrieval_engine(settings=settings)

    assert isinstance(engine, RetrievalEngine)
    assert engine.mcp_bridge is not None

    print("OK: MCPBridge wired successfully.")


if __name__ == "__main__":
    test_mcp_bridge_wiring_sanity()
