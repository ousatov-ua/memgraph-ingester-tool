from memgraph_ingester_tool.config import ToolConfig


def test_config_uses_primary_environment(monkeypatch):
    monkeypatch.setenv("MEMGRAPH_TOOLS_BOLT_URI", "bolt://memgraph:7687")
    monkeypatch.setenv("MEMGRAPH_TOOLS_USERNAME", "neo")
    monkeypatch.setenv("MEMGRAPH_TOOLS_PASSWORD", "secret")
    monkeypatch.setenv("MEMGRAPH_TOOLS_PROJECT", "demo")
    monkeypatch.setenv("MEMGRAPH_TOOLS_READ_ONLY", "true")
    monkeypatch.setenv("MEMGRAPH_TOOLS_QUERY_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("MEMGRAPH_TOOLS_EMBEDDING_DIMENSIONS", "768")

    config = ToolConfig.from_environment()

    assert config.bolt_uri == "bolt://memgraph:7687"
    assert config.username == "neo"
    assert config.password == "secret"
    assert config.default_project == "demo"
    assert config.read_only is True
    assert config.query_timeout_seconds == 12.5
    assert config.embedding_dimensions == 768


def test_config_falls_back_to_mcp_environment(monkeypatch):
    monkeypatch.setenv("MEMGRAPH_INGESTER_MCP_BOLT_URI", "bolt://legacy:7687")
    monkeypatch.setenv("MEMGRAPH_INGESTER_MCP_PROJECT", "legacy-demo")
    monkeypatch.setenv("MEMGRAPH_INGESTER_MCP_READ_ONLY", "true")

    config = ToolConfig.from_environment()

    assert config.bolt_uri == "bolt://legacy:7687"
    assert config.default_project == "legacy-demo"
    assert config.read_only is True


def test_config_primary_overrides_fallback(monkeypatch):
    monkeypatch.setenv("MEMGRAPH_TOOLS_BOLT_URI", "bolt://primary:7687")
    monkeypatch.setenv("MEMGRAPH_INGESTER_MCP_BOLT_URI", "bolt://legacy:7687")

    config = ToolConfig.from_environment()

    assert config.bolt_uri == "bolt://primary:7687"


def test_config_defaults_without_environment(monkeypatch):
    for name in (
        "MEMGRAPH_TOOLS_BOLT_URI",
        "MEMGRAPH_INGESTER_MCP_BOLT_URI",
        "MEMGRAPH_TOOLS_PROJECT",
        "MEMGRAPH_INGESTER_MCP_PROJECT",
        "MEMGRAPH_TOOLS_READ_ONLY",
        "MEMGRAPH_INGESTER_MCP_READ_ONLY",
    ):
        monkeypatch.delenv(name, raising=False)

    config = ToolConfig.from_environment()

    assert config.bolt_uri == "bolt://127.0.0.1:7687"
    assert config.default_project is None
    assert config.read_only is False
    assert config.embedding_model_name == "default"
    assert config.embedding_dimensions == 384
