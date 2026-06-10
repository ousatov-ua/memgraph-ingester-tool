"""Runtime configuration for the standalone tool."""

from __future__ import annotations

from dataclasses import dataclass
from os import getenv


def _optional_env(*names: str) -> str | None:
    for name in names:
        value = getenv(name)
        if value is not None and value != "":
            return value
    return None


def _bool_env(name: str, fallback: str, default: bool) -> bool:
    for n in (name, fallback):
        value = getenv(n)
        if value is not None and value != "":
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _float_env(name: str, fallback: str, default: float) -> float:
    for n in (name, fallback):
        value = getenv(n)
        if value is not None and value != "":
            try:
                return float(value)
            except ValueError:
                raise ValueError(
                    f"Environment variable {n!r} has an invalid float value: {value!r}."
                ) from None
    return default


def _int_env(name: str, fallback: str, default: int) -> int:
    for n in (name, fallback):
        value = getenv(n)
        if value is not None and value != "":
            try:
                return int(value)
            except ValueError:
                raise ValueError(
                    f"Environment variable {n!r} has an invalid integer value: {value!r}."
                ) from None
    return default


def _str_env(name: str, fallback: str, default: str) -> str:
    for n in (name, fallback):
        value = getenv(n)
        if value is not None and value != "":
            return value
    return default


@dataclass(frozen=True)
class ToolConfig:
    """Connection and embedding settings for the standalone tool.

    Environment variables (``MEMGRAPH_TOOLS_*`` take priority over
    ``MEMGRAPH_INGESTER_MCP_*`` for backwards compatibility):
    """

    bolt_uri: str = "bolt://127.0.0.1:7687"
    username: str | None = None
    password: str | None = None
    database: str | None = None
    default_project: str | None = None
    query_timeout_seconds: float = 30.0
    read_only: bool = False
    code_embedding_index_name: str = "code_chunk_embedding_v2"
    memory_embedding_index_name: str = "memory_chunk_embedding_v2"
    embedding_model_name: str = "default"
    embedding_dimensions: int = 384

    @classmethod
    def from_environment(cls) -> ToolConfig:
        """Load from environment variables.

        Checks ``MEMGRAPH_TOOLS_*`` first, then ``MEMGRAPH_INGESTER_MCP_*``
        for backwards compatibility with existing MCP configurations.
        """
        return cls(
            bolt_uri=_str_env(
                "MEMGRAPH_TOOLS_BOLT_URI",
                "MEMGRAPH_INGESTER_MCP_BOLT_URI",
                cls.bolt_uri,
            ),
            username=_optional_env("MEMGRAPH_TOOLS_USERNAME", "MEMGRAPH_INGESTER_MCP_USERNAME"),
            password=_optional_env("MEMGRAPH_TOOLS_PASSWORD", "MEMGRAPH_INGESTER_MCP_PASSWORD"),
            database=_optional_env("MEMGRAPH_TOOLS_DATABASE", "MEMGRAPH_INGESTER_MCP_DATABASE"),
            default_project=_optional_env(
                "MEMGRAPH_TOOLS_PROJECT", "MEMGRAPH_INGESTER_MCP_PROJECT"
            ),
            query_timeout_seconds=_float_env(
                "MEMGRAPH_TOOLS_QUERY_TIMEOUT_SECONDS",
                "MEMGRAPH_INGESTER_MCP_QUERY_TIMEOUT_SECONDS",
                cls.query_timeout_seconds,
            ),
            read_only=_bool_env(
                "MEMGRAPH_TOOLS_READ_ONLY",
                "MEMGRAPH_INGESTER_MCP_READ_ONLY",
                cls.read_only,
            ),
            code_embedding_index_name=_str_env(
                "MEMGRAPH_TOOLS_CODE_EMBEDDING_INDEX",
                "MEMGRAPH_INGESTER_MCP_CODE_EMBEDDING_INDEX",
                cls.code_embedding_index_name,
            ),
            memory_embedding_index_name=_str_env(
                "MEMGRAPH_TOOLS_MEMORY_EMBEDDING_INDEX",
                "MEMGRAPH_INGESTER_MCP_MEMORY_EMBEDDING_INDEX",
                cls.memory_embedding_index_name,
            ),
            embedding_model_name=_str_env(
                "MEMGRAPH_TOOLS_EMBEDDING_MODEL",
                "MEMGRAPH_INGESTER_MCP_EMBEDDING_MODEL",
                cls.embedding_model_name,
            ),
            embedding_dimensions=_int_env(
                "MEMGRAPH_TOOLS_EMBEDDING_DIMENSIONS",
                "MEMGRAPH_INGESTER_MCP_EMBEDDING_DIMENSIONS",
                cls.embedding_dimensions,
            ),
        )
