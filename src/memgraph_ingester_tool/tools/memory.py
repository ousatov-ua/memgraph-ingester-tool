"""Memory-node endpoints: orientation, search, CRUD, chunk and embedding refresh."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

from memgraph_ingester_tool import queries as Q
from memgraph_ingester_tool.db import ToolError
from memgraph_ingester_tool.schema import MEMORY_SPECS, TARGET_TYPES
from memgraph_ingester_tool.tools._base import MemgraphToolsBase
from memgraph_ingester_tool.tools._memory_support import (
    CONTROLLED_VALUES,
    _memory_label_predicate,
    _memory_schema_entry,
    _memory_spec,
    _target_match,
)
from memgraph_ingester_tool.tools._support import _bounded_limit
from memgraph_ingester_tool.tools._vector_index import _select_vector_index_label


class MemoryTools(MemgraphToolsBase):
    """memory_* endpoints plus delete_memory."""

    def memory_orientation(
        self,
        project: str | None = None,
        compact: bool = False,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        rule_projection = (
            "rule.id AS id, rule.severity AS severity, rule.title AS title"
            if compact
            else """
                       rule.id AS id, rule.severity AS severity, rule.title AS title,
                       rule.description AS description
            """.strip()
        )
        finding_projection = (
            "finding.id AS id, finding.type AS type, finding.title AS title"
            if compact
            else """
                       finding.id AS id, finding.type AS type, finding.title AS title,
                       finding.summary AS summary
            """.strip()
        )
        task_projection = (
            """
                       task.id AS id, task.title AS title, task.status AS status,
                       task.priority AS priority
            """.strip()
            if compact
            else """
                       task.id AS id, task.title AS title, task.status AS status,
                       task.priority AS priority, task.description AS description
            """.strip()
        )
        risk_projection = (
            "risk.id AS id, risk.title AS title, risk.severity AS severity"
            if compact
            else """
                       risk.id AS id, risk.title AS title, risk.severity AS severity,
                       risk.mitigation AS mitigation
            """.strip()
        )
        return self._finalize_response(
            {
                "project": project_name,
                "rules": self.client.run(
                    Q.MEMORY_ORIENTATION_RULES.replace("__RETURN_PROJECTION__", rule_projection),
                    {"project": project_name},
                ),
                "openFindings": self.client.run(
                    Q.MEMORY_ORIENTATION_OPEN_FINDINGS.replace(
                        "__RETURN_PROJECTION__", finding_projection
                    ),
                    {"project": project_name},
                ),
                "activeTasks": self.client.run(
                    Q.MEMORY_ORIENTATION_ACTIVE_TASKS.replace(
                        "__RETURN_PROJECTION__", task_projection
                    ),
                    {"project": project_name},
                ),
                "openQuestions": self.client.run(
                    Q.MEMORY_ORIENTATION_OPEN_QUESTIONS,
                    {"project": project_name},
                ),
                "openRisks": self.client.run(
                    Q.MEMORY_ORIENTATION_OPEN_RISKS.replace(
                        "__RETURN_PROJECTION__", risk_projection
                    ),
                    {"project": project_name},
                ),
            }
        )

    def memory_schema(self, memory_type: str | None = None) -> dict[str, Any]:
        memory_types = [memory_type] if memory_type is not None else sorted(MEMORY_SPECS)
        schemas = {type_name: _memory_schema_entry(type_name) for type_name in memory_types}
        return {
            "memoryTypes": schemas,
            "targetTypes": sorted(TARGET_TYPES),
        }

    def memory_search(
        self,
        query: str,
        project: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        index_name, _ = self._select_vector_index(
            self.config.memory_embedding_index_name,
            project_name,
        )
        rows = self.client.run(
            Q.MEMORY_SEARCH,
            {
                "index": index_name,
                "project": project_name,
                "query": query,
                "embed_config": self._embedding_text_config(
                    project_name,
                    preferred_chunk_label="MemoryChunk",
                ),
                "limit": _bounded_limit(limit, default=5, maximum=20),
            },
        )
        return self._finalize_response({"project": project_name, "query": query, "hits": rows})

    def memory_get(
        self,
        memory_id: str,
        project: str | None = None,
        *,
        finalize: bool = True,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        rows = self.client.run(
            Q.MEMORY_GET.replace("__MEMORY_LABEL_PREDICATE__", _memory_label_predicate("memory")),
            {"project": project_name, "memory_id": memory_id},
        )
        response = {"project": project_name, "memory": rows[0] if rows else None}
        return self._finalize_response(response) if finalize else response

    def delete_memory(self, memory_id: str, project: str | None = None) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        rows = self.client.run(
            Q.MEMORY_DELETE_READ.replace(
                "__MEMORY_LABEL_PREDICATE__", _memory_label_predicate("memory")
            ),
            {"project": project_name, "memory_id": memory_id},
        )
        if not rows:
            return self._finalize_response(
                {
                    "project": project_name,
                    "deleted": False,
                    "memory": None,
                    "chunkIds": [],
                    "orphanCodeRefsDeleted": 0,
                }
            )

        memory = rows[0]
        code_refs = memory.get("codeRefs", [])
        self.client.run(
            Q.MEMORY_DELETE_WRITE.replace(
                "__MEMORY_LABEL_PREDICATE__", _memory_label_predicate("memory")
            ),
            {"project": project_name, "memory_id": memory_id},
            write=True,
        )

        orphan_deleted = 0
        if code_refs:
            orphan_rows = self.client.run(
                Q.MEMORY_DELETE_ORPHAN_REFS,
                {"project": project_name, "code_refs": code_refs},
                write=True,
            )
            orphan_deleted = orphan_rows[0].get("deleted", 0) if orphan_rows else 0

        return self._finalize_response(
            {
                "project": project_name,
                "deleted": True,
                "memory": {
                    "labels": memory.get("labels", []),
                    "properties": memory.get("properties", {}),
                },
                "chunkIds": memory.get("chunkIds", []),
                "codeRefs": code_refs,
                "orphanCodeRefsDeleted": orphan_deleted,
            }
        )

    def memory_upsert(
        self,
        memory_type: str,
        memory_id: str,
        fields: Mapping[str, Any],
        project: str | None = None,
        code_ref: Mapping[str, str] | None = None,
        refresh_chunk: bool = True,
        embed: bool = True,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        spec = _memory_spec(memory_type)
        properties = self._validated_memory_fields(memory_type, fields)
        rows = self.client.run(
            Q.MEMORY_UPSERT.replace("__LABEL__", spec.label).replace(
                "__RELATION__", spec.relation
            ),
            {"project": project_name, "memory_id": memory_id, "properties": properties},
            write=True,
        )
        link_result = None
        if code_ref is not None:
            link_result = self.memory_link_code_ref(
                memory_type,
                memory_id,
                code_ref.get("target_type") or code_ref.get("targetType") or "",
                code_ref.get("key") or "",
                project_name,
                refresh_chunk=False,
            )
        chunk_result = None
        if refresh_chunk:
            chunk_result = self.memory_refresh_chunk(
                memory_type,
                memory_id,
                project_name,
                embed=embed,
            )
        return self._finalize_response(
            {
                "project": project_name,
                "memory": rows[0] if rows else None,
                "codeRef": link_result,
                "chunk": chunk_result,
            }
        )

    def memory_update_status(
        self,
        memory_type: str,
        memory_id: str,
        status: str,
        project: str | None = None,
        refresh_chunk: bool = True,
        embed: bool = True,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        spec = _memory_spec(memory_type)
        if "status" not in spec.fields:
            raise ToolError(f"{memory_type} does not have a status field.")
        self._validate_controlled_value(memory_type, "status", status)
        rows = self.client.run(
            Q.MEMORY_UPDATE_STATUS.replace("__LABEL__", spec.label),
            {"project": project_name, "memory_id": memory_id, "status": status},
            write=True,
        )
        chunk_result = None
        if refresh_chunk:
            chunk_result = self.memory_refresh_chunk(
                memory_type,
                memory_id,
                project_name,
                embed=embed,
            )
        return self._finalize_response(
            {
                "project": project_name,
                "memory": rows[0] if rows else None,
                "chunk": chunk_result,
            }
        )

    def memory_link_code_ref(
        self,
        memory_type: str,
        memory_id: str,
        target_type: str,
        key: str,
        project: str | None = None,
        *,
        refresh_chunk: bool = True,
        embed: bool = True,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        spec = _memory_spec(memory_type)
        target_label, predicate = _target_match(target_type)
        rows = self.client.run(
            Q.MEMORY_LINK_CODE_REF.replace("__LABEL__", spec.label)
            .replace("__TARGET_LABEL__", target_label)
            .replace("__TARGET_PREDICATE__", predicate),
            {
                "project": project_name,
                "memory_id": memory_id,
                "target_type": target_type,
                "target_key": key,
            },
            write=True,
        )
        chunk_result = None
        if rows and refresh_chunk:
            chunk_result = self.memory_refresh_chunk(
                memory_type,
                memory_id,
                project_name,
                embed=embed,
            )
        return self._finalize_response(
            {
                "project": project_name,
                "resolved": bool(rows),
                "links": rows,
                "chunk": chunk_result,
            }
        )

    def memory_refresh_chunk(
        self,
        memory_type: str,
        memory_id: str,
        project: str | None = None,
        *,
        embed: bool = True,
        finalize: bool = True,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        spec = _memory_spec(memory_type)
        memory = self.memory_get(memory_id, project_name, finalize=False).get("memory")
        if memory is None:
            raise ToolError(f"Memory node {memory_id!r} was not found.")

        text = self._memory_chunk_text(memory_type, memory)
        text_hash = sha256(text.encode("utf-8")).hexdigest()
        chunk_id = f"MCH-{memory_id}"
        rows = self.client.run(
            Q.MEMORY_REFRESH_CHUNK.replace("__LABEL__", spec.label),
            {
                "project": project_name,
                "memory_id": memory_id,
                "chunk_id": chunk_id,
                "memory_type": memory_type,
                "text": text,
                "text_hash": text_hash,
            },
            write=True,
        )
        embedding_result = None
        if embed:
            embedding_result = self.memory_refresh_embeddings(
                [chunk_id], project_name, finalize=False
            )
            if rows and chunk_id in set(embedding_result.get("embedded", [])):
                rows[0]["dirty"] = False
        response = {
            "project": project_name,
            "chunk": rows[0] if rows else None,
            "embedding": embedding_result,
        }
        return self._finalize_response(response) if finalize else response

    def memory_refresh_embeddings(
        self,
        chunk_ids: Sequence[str],
        project: str | None = None,
        *,
        finalize: bool = True,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        ids = [chunk_id for chunk_id in dict.fromkeys(chunk_ids) if chunk_id]
        if not ids:
            response = {"project": project_name, "embedded": []}
            return self._finalize_response(response) if finalize else response

        model_name = self._resolved_embedding_model_name(project_name, "MemoryChunk")
        index_name, vector_index_rows = self._select_vector_index(
            self.config.memory_embedding_index_name,
            project_name,
        )
        index_label = _select_vector_index_label(
            self.config.memory_embedding_index_name,
            project_name,
            index_name,
            vector_index_rows,
            chunk_label="MemoryChunk",
        )
        dimension = self._resolved_embedding_dimensions(
            project_name,
            base_index_name=self.config.memory_embedding_index_name,
            selected_index_name=index_name,
            vector_index_rows=vector_index_rows,
        )
        self.client.run(
            Q.MEMORY_TAG_VECTOR_INDEX_LABEL.replace("__VECTOR_INDEX_LABEL__", index_label),
            {"project": project_name, "ids": ids},
            write=True,
        )
        pending = self.client.run(
            Q.MEMORY_REFRESH_EMBEDDINGS_PENDING,
            {
                "project": project_name,
                "ids": ids,
                "model_name": model_name,
                "dimension": dimension,
            },
        )
        pending_ids = [row["id"] for row in pending]
        if not pending_ids:
            response = {"project": project_name, "embedded": []}
            return self._finalize_response(response) if finalize else response

        result = self.client.run(
            Q.MEMORY_REFRESH_EMBEDDINGS_EMBED,
            {
                "project": project_name,
                "ids": pending_ids,
                "embed_config": self._node_sentence_config(
                    project_name,
                    preferred_chunk_label="MemoryChunk",
                ),
            },
            write=True,
        )
        embed_success = result[0].get("success", False) if result else False
        if not embed_success:
            response = {"project": project_name, "embedded": [], "result": result}
            return self._finalize_response(response) if finalize else response

        dimension = result[0].get("dimension") if result else self.config.embedding_dimensions
        self.client.run(
            Q.MEMORY_REFRESH_EMBEDDINGS_MARK,
            {
                "project": project_name,
                "ids": pending_ids,
                "model_name": model_name,
                "dimension": dimension,
            },
            write=True,
        )
        response = {"project": project_name, "embedded": pending_ids, "result": result}
        return self._finalize_response(response) if finalize else response

    def _validated_memory_fields(
        self,
        memory_type: str,
        fields: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(fields, Mapping):
            raise ToolError("fields must be an object.")

        spec = _memory_spec(memory_type)
        unknown = sorted(set(fields) - spec.fields)
        if unknown:
            allowed = ", ".join(sorted(spec.fields))
            raise ToolError(
                f"Unsupported {memory_type} field(s): {', '.join(unknown)}. Allowed: {allowed}."
            )

        properties: dict[str, Any] = {}
        for key, value in fields.items():
            if value is None:
                continue
            normalized = str(value) if (memory_type, key) in CONTROLLED_VALUES else value
            self._validate_controlled_value(memory_type, key, normalized)
            properties[key] = normalized
        return properties

    def _validate_controlled_value(self, memory_type: str, field: str, value: Any) -> None:
        allowed = CONTROLLED_VALUES.get((memory_type, field))
        if allowed is not None and value not in allowed:
            joined = ", ".join(sorted(allowed))
            raise ToolError(f"{memory_type}.{field} must be one of: {joined}.")

    def _memory_chunk_text(self, memory_type: str, memory: Mapping[str, Any]) -> str:
        properties = memory.get("properties") or {}
        refs = memory.get("codeRefs") or []
        spec = _memory_spec(memory_type)
        field_parts = []
        for key in sorted(spec.fields):
            value = properties.get(key)
            if value not in (None, ""):
                field_parts.append(f"{key}: {value}")
        ref_parts = [f"{ref.get('targetType')} {ref.get('key')}" for ref in refs]
        refs_text = ", ".join(ref_parts) if ref_parts else "none"
        return (
            f"{memory_type}: {properties.get('id')}. "
            f"{'; '.join(field_parts)}. "
            f"CodeRefs: {refs_text}."
        )
