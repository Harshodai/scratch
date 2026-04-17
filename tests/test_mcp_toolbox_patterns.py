"""
Sanity tests for the 3 stolen MCP Toolbox design patterns.

1. Source/Tool Separation
2. Declarative YAML Config
3. Prebuilt Config Templates
"""

import os
import pytest
import sqlite3
from pathlib import Path
from centrag.mcp.bridge import MCPBridge
from centrag.mcp.source_registry import SourceRegistry, SQLSourceConfig
from centrag.mcp.tool_registry import ToolRegistry, Toolset

@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('Alice'), ('Bob')")
    conn.commit()
    conn.close()
    return f"sqlite:///{db_path}"

@pytest.mark.asyncio
async def test_steal_1_source_tool_separation(temp_db):
    """Verify Steal #1: Source can be registered and tools generated separately."""
    bridge = MCPBridge()
    
    # 1. Register Source
    success = bridge.register_dynamic_db("test_db", temp_db)
    assert success is True
    
    # 2. Check Source Registry
    source = bridge.source_registry.get("test_db")
    assert source is not None
    assert source.source_type == "sqlite"
    
    # 3. Check Tool Registry (auto-generated tools)
    tools = bridge.tool_registry.list_tools()
    assert "test_db.execute_read_query" in tools
    assert "test_db.query_users" in tools
    assert "test_db.describe_schema" in tools
    
    # 4. Invoke a tool
    result = await bridge.call_tool("test_db.query_users", {"limit": 1})
    assert "Alice" in result
    assert "Bob" not in result # because limit 1

@pytest.mark.asyncio
async def test_steal_2_declarative_yaml(temp_db, tmp_path):
    """Verify Steal #2: YAML config loading works."""
    yaml_path = tmp_path / "mcp_tools.yaml"
    # YAML and Windows backslashes don't play well in double quotes (unicode escape error)
    # So we force forward slashes for the DB path string.
    safe_db_path = str(temp_db).replace("\\", "/")
    yaml_content = f"""
sources:
  my_sqlite:
    kind: sqlite
    connection_string: "{safe_db_path}"
    read_only: true
tools:
  count_users:
    kind: sql-query
    source: my_sqlite
    description: "Get user count"
    statement: "SELECT count(*) as count FROM users"
toolsets:
  admin:
    - count_users
    - my_sqlite.describe_schema
"""
    yaml_path.write_text(yaml_content)
    
    bridge = MCPBridge()
    summary = bridge.load_config(yaml_path)
    
    assert summary["sources"] == 1
    assert summary["tools"] == 1
    assert summary["toolsets"] == 1
    
    # Verify the custom tool works
    result = await bridge.call_tool("count_users", {})
    assert '"count": 2' in result
    
    # Verify the toolset
    toolset = bridge.tool_registry.get_toolset("admin")
    assert len(toolset) == 2
    assert toolset[0].name == "count_users"

def test_steal_3_prebuilt_templates():
    """Verify Steal #3: Prebuilt templates are discoverable."""
    bridge = MCPBridge()
    templates = bridge.list_prebuilt_templates()
    
    assert "sqlite" in templates
    assert "postgres" in templates
    assert "mysql" in templates
    
    sqlite_tpl = bridge.get_prebuilt_template("sqlite")
    assert "kind: sqlite" in sqlite_tpl
    assert "execute_read_query" in sqlite_tpl
