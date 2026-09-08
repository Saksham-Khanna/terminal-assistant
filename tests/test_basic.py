"""Basic tests for agentic-ide package."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_import_agent():
    """Test that agent module can be imported."""
    import agent
    assert agent is not None


def test_import_tools():
    """Test that tools module can be imported."""
    from agent.tools import TOOL_SCHEMAS, execute_tool
    assert len(TOOL_SCHEMAS) > 0
    assert callable(execute_tool)


def test_import_core():
    """Test that core module can be imported."""
    from agent.core import Agent
    assert Agent is not None


def test_tool_schemas_structure():
    """Test that tool schemas have required fields."""
    from agent.tools import TOOL_SCHEMAS
    
    for tool in TOOL_SCHEMAS:
        assert "name" in tool, f"Tool missing 'name': {tool}"
        assert "description" in tool, f"Tool missing 'description': {tool}"
        assert "input_schema" in tool, f"Tool missing 'input_schema': {tool}"
        
        schema = tool["input_schema"]
        assert "type" in schema, f"Schema missing 'type': {tool['name']}"
        assert "properties" in schema, f"Schema missing 'properties': {tool['name']}"


def test_workspace_root():
    """Test that WORKSPACE_ROOT is set correctly."""
    from agent.tools import WORKSPACE_ROOT
    assert os.path.isabs(WORKSPACE_ROOT)
    assert os.path.exists(WORKSPACE_ROOT) or WORKSPACE_ROOT.endswith("workspace")


def test_execute_unknown_tool():
    """Test that unknown tool returns error message."""
    from agent.tools import execute_tool
    result = execute_tool("nonexistent_tool", {})
    assert "Error" in result
    assert "unknown tool" in result.lower()
