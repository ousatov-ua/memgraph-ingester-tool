"""Shared base for all tool mixins: connection, project resolution, response finishing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from memgraph_ingester_tool import queries as Q
from memgraph_ingester_tool.config import ToolConfig
from memgraph_ingester_tool.db import ToolClient, ToolError
from memgraph_ingester_tool.tools._guards import _ensure_project_scoped, _ensure_read_only_query
from memgraph_ingester_tool.tools._memory_support import MEMORY_CHUNK_EXCLUDED_PROPERTIES
from memgraph_ingester_tool.tools._support import (
    _bounded_limit,
    _format_response,
    _with_result_meta,
)
from memgraph_ingester_tool.tools._vector_index import (
    _select_vector_index_name,
    _vector_index_names,
)


class MemgraphToolsBase:
    """Connection handling and response plumbing shared by every tool mixin."""

    def __init__(
        self,
        config: ToolConfig | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self.config = config or ToolConfig.from_environment()
        self.client = client or ToolClient(self.config)

    def resolve_project(self, project: str | None) -> str:
        resolved = project or self.config.default_project
        if resolved is None or resolved.strip() == "":
            raise ToolError(
                "Project is required. Pass project or set MEMGRAPH_TOOLS_PROJECT."
            )
        return resolved

    def _finalize_response(
        self,
        response: dict[str, Any],
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = _format_response(response, output_format)
        result.pop("project", None)
        return result

    def _select_vector_index_name(self, base_index_name: str, project: str) -> str:
        return _select_vector_index_name(
            base_index_name,
            project,
            _vector_index_names(self.client.run("SHOW VECTOR INDEX INFO")),
        )

    def _embedding_text_config(self) -> dict[str, Any]:
        """Config for embeddings.text: pin the model when one is explicitly configured.

        Keeps query embeddings on the same model as document embeddings instead of
        relying implicitly on the module default.
        """
        model_name = (self.config.embedding_model_name or "").strip()
        if not model_name or model_name == "default":
            return {}
        return {"model_name": model_name}

    def _node_sentence_config(self) -> dict[str, Any]:
        """Config for embeddings.node_sentence on MemoryChunk nodes.

        Excludes metadata properties exactly like the ingester does so both refresh
        paths produce embeddings from the same text.
        """
        config = self._embedding_text_config()
        config["embedding_property"] = "embedding"
        config["excluded_properties"] = list(MEMORY_CHUNK_EXCLUDED_PROPERTIES)
        return config

    def server_status(self, project: str | None = None) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        vector_index_rows = self.client.run("SHOW VECTOR INDEX INFO")
        available_index_names = _vector_index_names(vector_index_rows)
        vector_index_names = {
            _select_vector_index_name(
                self.config.code_embedding_index_name,
                project_name,
                available_index_names,
            ),
            _select_vector_index_name(
                self.config.memory_embedding_index_name,
                project_name,
                available_index_names,
            ),
        }
        languages = self.client.run(
            Q.SERVER_STATUS_LANGUAGES,
            {"project": project_name},
        )
        inventory = self.client.run(
            Q.SERVER_STATUS_INVENTORY,
            {"project": project_name},
        )
        memories = self.client.run(
            Q.SERVER_STATUS_MEMORIES,
            {"project": project_name},
        )
        indexes = [row for row in vector_index_rows if row.get("index_name") in vector_index_names]
        return {
            "project": project_name,
            "languages": languages,
            "inventory": inventory[0] if inventory else {},
            "memoryCounts": memories,
            "vectorIndexes": indexes,
        }

    def raw_read_cypher(
        self,
        query: str,
        project: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        limit: int = 200,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        _ensure_read_only_query(query)
        _ensure_project_scoped(query)
        params = dict(parameters or {})
        bounded_limit = _bounded_limit(limit, default=200, maximum=500)
        params.setdefault("project", project_name)
        params.setdefault("limit", bounded_limit)
        rows = self.client.run(query, params)
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "rows": rows},
                rows,
                limit=bounded_limit,
            ),
            output_format,
        )
