"""Semantic (vector) and lexical code search over RAG chunks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from memgraph_ingester_tool import queries as Q
from memgraph_ingester_tool.db import ToolError
from memgraph_ingester_tool.tools._base import MemgraphToolsBase
from memgraph_ingester_tool.tools._search_support import (
    DEFAULT_RAG_ROLES,
    _dedupe_chunk_rows,
    _lexical_query_terms,
    _passes_chunk_filters,
    _query_variants,
    _rrf_fuse,
)
from memgraph_ingester_tool.tools._support import (
    DISCOVERY_LIMIT,
    _bounded_limit,
    _bounded_text_limit,
    _compact_owner,
    _compact_text,
    _normalize_lower_list,
    _normalize_string_list,
    _with_result_meta,
)


class CodeSearchTools(MemgraphToolsBase):
    """code_search / code_text_search and their shared lexical query leg."""

    def code_search(
        self,
        query: str,
        project: str | None = None,
        limit: int = DISCOVERY_LIMIT,
        include_tests: bool = False,
        include_text: bool = False,
        text_limit: int = 160,
        dedupe_by_source: bool = True,
        kinds: Sequence[str] | str | None = None,
        path_prefixes: Sequence[str] | str | None = None,
        path_contains: str | None = None,
        owner_fragment: str | None = None,
        min_score: float = 0.0,
        include_secondary: bool = False,
        rag_roles: Sequence[str] | str | None = None,
        include_keys: bool = False,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        index_name, _ = self._select_vector_index(
            self.config.code_embedding_index_name,
            project_name,
        )
        bounded_limit = _bounded_limit(limit, default=DISCOVERY_LIMIT, maximum=25)
        bounded_text_limit = _bounded_text_limit(text_limit)
        role_filter = _normalize_string_list(rag_roles)
        if not role_filter and not include_secondary:
            role_filter = list(DEFAULT_RAG_ROLES)
        kind_filter = frozenset(_normalize_string_list(kinds))
        path_prefix_filter = _normalize_string_list(path_prefixes)
        path_contains_filter = (path_contains or "").strip()
        owner_filter = (owner_fragment or "").strip()
        filter_active = bool(
            kind_filter
            or path_prefix_filter
            or path_contains_filter
            or owner_filter
            or min_score > 0
        )
        fetch_multiplier = 10 if filter_active else (6 if role_filter else 3)
        fetch_limit = (
            min(bounded_limit * fetch_multiplier, 250) if dedupe_by_source else bounded_limit
        )
        role_projection = "effectiveRole AS ragRole," if include_keys else ""
        return_projection = (
            f"""
                   kind,
                   sourceId,
                   owner,
                   name,
                   path,
                   {role_projection}
                   startLine, endLine,
                   round(similarity * 10000) / 10000 AS score,
                   chunk.text AS text
            """
            if include_text
            else f"""
                   kind,
                   sourceId,
                   owner,
                   name,
                   path,
                   {role_projection}
                   startLine, endLine,
                   round(similarity * 10000) / 10000 AS score
            """
        )
        search_query = Q.CODE_SEARCH.replace("__RETURN_PROJECTION__", return_projection.strip())
        variants = _query_variants(query)
        lexical_terms = _lexical_query_terms(query) if dedupe_by_source else []
        vector_unavailable = False
        raw_rows: list[dict[str, Any]] = []
        try:
            raw_rows = self.client.run(
                search_query,
                {
                    "index": index_name,
                    "project": project_name,
                    "queries": variants,
                    "embed_config": self._embedding_text_config(
                        project_name,
                        preferred_chunk_label="CodeChunk",
                    ),
                    "limit": fetch_limit,
                    "include_tests": include_tests,
                    "rag_roles": role_filter,
                    "kinds": list(kind_filter),
                    "path_prefixes": path_prefix_filter,
                    "path_contains": path_contains_filter,
                    "owner_fragment": owner_filter,
                    "min_score": min_score,
                },
            )
        except ToolError:
            if not lexical_terms:
                raise
            vector_unavailable = True
        raw_lexical_rows: list[dict[str, Any]] = []
        if lexical_terms:
            raw_lexical_rows = self._lexical_chunk_rows(
                project_name,
                required_terms=[],
                optional_terms=lexical_terms,
                limit=fetch_limit,
                include_tests=include_tests,
                include_text=include_text,
                kind_filter=list(kind_filter),
                role_filter=role_filter,
                path_contains_filter=path_contains_filter,
            )

        def passes(row: Mapping[str, Any]) -> bool:
            return _passes_chunk_filters(
                row,
                kind_filter=kind_filter,
                path_prefix_filter=path_prefix_filter,
                path_contains_filter=path_contains_filter,
                owner_filter=owner_filter,
                min_score=min_score,
            )

        filtered_vector = [row for row in raw_rows if passes(row)]
        if dedupe_by_source:
            rows = _rrf_fuse(
                _dedupe_chunk_rows(filtered_vector),
                _dedupe_chunk_rows([row for row in raw_lexical_rows if passes(row)]),
            )[:bounded_limit]
        else:
            rows = filtered_vector[:bounded_limit]
        for row in rows:
            if include_text:
                row["text"] = _compact_text(row.get("text"), bounded_text_limit)
            else:
                row.pop("text", None)
            if not include_keys:
                row.pop("sourceId", None)
                row.pop("ragRole", None)
            row["owner"] = _compact_owner(row.get("owner"), row.get("name"))
        saturated = len(raw_rows) >= fetch_limit
        extra: dict[str, Any] = {}
        if saturated:
            extra["candidateLimitReached"] = True
        if vector_unavailable:
            extra["vectorUnavailable"] = True
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "hits": rows},
                rows,
                limit=bounded_limit,
                extra=extra or None,
            ),
            output_format,
        )

    def _lexical_chunk_rows(
        self,
        project_name: str,
        *,
        required_terms: Sequence[str],
        optional_terms: Sequence[str],
        limit: int,
        include_tests: bool,
        include_text: bool,
        kind_filter: Sequence[str],
        role_filter: Sequence[str],
        path_contains_filter: str,
    ) -> list[dict[str, Any]]:
        """Run the shared lexical chunk query; rows keep sourceId/ragRole for callers."""
        search_terms = list(required_terms) + list(optional_terms)
        text_projection = ", chunk.text AS text" if include_text else ""
        return self.client.run(
            Q.LEXICAL_CHUNK_ROWS.replace("__TEXT_PROJECTION__", text_projection),
            {
                "project": project_name,
                "all_terms": list(required_terms),
                "any_terms": list(optional_terms),
                "search_terms": search_terms,
                "kinds": list(kind_filter),
                "rag_roles": list(role_filter),
                "path_contains": path_contains_filter,
                "include_tests": include_tests,
                "limit": limit,
            },
        )

    def code_text_search(
        self,
        query: str | None = None,
        project: str | None = None,
        all_terms: Sequence[str] | str | None = None,
        any_terms: Sequence[str] | str | None = None,
        limit: int = DISCOVERY_LIMIT,
        include_tests: bool = False,
        include_text: bool = False,
        text_limit: int = 160,
        kinds: Sequence[str] | str | None = None,
        include_secondary: bool = False,
        rag_roles: Sequence[str] | str | None = None,
        path_contains: str | None = None,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        bounded_limit = _bounded_limit(limit, default=DISCOVERY_LIMIT, maximum=50)
        bounded_text_limit = _bounded_text_limit(text_limit)
        required_terms = _normalize_lower_list(all_terms)
        optional_terms = _normalize_lower_list(any_terms)
        if query and not required_terms and not optional_terms:
            optional_terms = _lexical_query_terms(query)
        if not required_terms and not optional_terms:
            raise ToolError("Provide query, all_terms, or any_terms.")
        kind_filter = _normalize_string_list(kinds)
        role_filter = _normalize_string_list(rag_roles)
        if not role_filter and not include_secondary:
            role_filter = list(DEFAULT_RAG_ROLES)
        path_contains_filter = (path_contains or "").strip()
        rows = self._lexical_chunk_rows(
            project_name,
            required_terms=required_terms,
            optional_terms=optional_terms,
            limit=bounded_limit,
            include_tests=include_tests,
            include_text=include_text,
            kind_filter=kind_filter,
            role_filter=role_filter,
            path_contains_filter=path_contains_filter,
        )
        for row in rows:
            if include_text:
                row["text"] = _compact_text(row.get("text"), bounded_text_limit)
            else:
                row.pop("text", None)
            row.pop("ragRole", None)
            row.pop("sourceId", None)
            row["owner"] = _compact_owner(row.get("owner"), row.get("name"))
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "hits": rows},
                rows,
                limit=bounded_limit,
            ),
            output_format,
        )
