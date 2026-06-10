"""Exact lookups for types, methods, fields, and files."""

from __future__ import annotations

from typing import Any

from memgraph_ingester_tool import queries as Q
from memgraph_ingester_tool.db import ToolError
from memgraph_ingester_tool.tools._base import MemgraphToolsBase
from memgraph_ingester_tool.tools._support import (
    LOOKUP_LIMIT,
    MEMBER_LIMIT,
    _bounded_limit,
    _bounded_skip,
    _first,
    _method_name,
    _overfetch_limit,
    _trim_overfetch,
    _with_result_meta,
)


class CodeLookupTools(MemgraphToolsBase):
    """code_lookup_type / code_lookup_methods / code_lookup_field / code_lookup_file."""

    def code_lookup_type(
        self,
        project: str | None = None,
        type_name: str | None = None,
        fqn: str | None = None,
        include_members: bool = False,
        include_tests: bool = False,
        member_limit: int = MEMBER_LIMIT,
        member_summary: bool = False,
        limit: int = LOOKUP_LIMIT,
        include_count: bool = False,
        compact: bool = True,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        if not type_name and not fqn:
            raise ToolError("Provide either type_name or fqn.")
        bounded_limit = _bounded_limit(limit, default=LOOKUP_LIMIT, maximum=100)
        bounded_member_limit = _bounded_limit(member_limit, default=MEMBER_LIMIT, maximum=200)
        predicate = "t.fqn = $fqn" if fqn else "t.name = $type_name"
        member_count_cypher = (
            """
            OPTIONAL MATCH (t)-[:DECLARES]->(m_cnt:Method {project: $project})
            WITH t, files, count(m_cnt) AS methodCount
            OPTIONAL MATCH (t)-[:DECLARES]->(f_cnt:Field {project: $project})
            WITH t, files, methodCount, count(f_cnt) AS fieldCount
            """
            if (member_summary and not include_members)
            else ""
        )
        member_count_cols = (
            ", methodCount, fieldCount" if (member_summary and not include_members) else ""
        )
        extra_type_cols = (
            ""
            if compact
            else (
                "t.visibility AS visibility, t.isExternal AS isExternal, "
                "t.language AS language, t.framework AS framework, "
                "t.modulePath AS modulePath, "
            )
        )
        types = self.client.run(
            Q.CODE_LOOKUP_TYPE
            .replace("__PREDICATE__", predicate)
            .replace("__MEMBER_COUNT_CYPHER__", member_count_cypher)
            .replace("__EXTRA_TYPE_COLS__", extra_type_cols)
            .replace("__MEMBER_COUNT_COLS__", member_count_cols),
            {
                "project": project_name,
                "type_name": type_name,
                "fqn": fqn,
                "limit": _overfetch_limit(bounded_limit, include_count),
                "include_tests": include_tests,
            },
        )
        types, page_extra = _trim_overfetch(
            types,
            skip=0,
            limit=bounded_limit,
            include_count=include_count,
        )
        total_count = None
        if include_count:
            count_rows = self.client.run(
                Q.CODE_LOOKUP_TYPE_COUNT.replace("__PREDICATE__", predicate),
                {
                    "project": project_name,
                    "type_name": type_name,
                    "fqn": fqn,
                    "include_tests": include_tests,
                },
            )
            total_count = count_rows[0].get("count", 0) if count_rows else len(types)
        if member_summary and not include_members:
            for item in types:
                item["memberCounts"] = {
                    "methods": item.pop("methodCount", 0),
                    "fields": item.pop("fieldCount", 0),
                }
        if include_members:
            for item in types:
                item_fqn = item.get("fqn")
                if not item_fqn:
                    continue
                method_projection = (
                    """
                    m.signature AS signature, m.name AS name, m.startLine AS startLine,
                    m.endLine AS endLine
                    """
                    if compact
                    else """
                    m.signature AS signature, m.name AS name, m.startLine AS startLine,
                    m.endLine AS endLine, m.returnType AS returnType,
                    m.visibility AS visibility, m.isStatic AS isStatic,
                    m.isSynthetic AS isSynthetic
                    """
                )
                item["methods"] = self.client.run(
                    Q.CODE_LOOKUP_TYPE_MEMBERS_METHODS.replace(
                        "__METHOD_PROJECTION__", method_projection.strip()
                    ),
                    {"project": project_name, "fqn": item_fqn, "limit": bounded_member_limit},
                )
                field_projection = (
                    "field.fqn AS fqn, field.name AS name"
                    if compact
                    else """
                    field.fqn AS fqn, field.name AS name, field.type AS type,
                    field.visibility AS visibility, field.isStatic AS isStatic,
                    field.kind AS kind
                    """
                )
                item["fields"] = self.client.run(
                    Q.CODE_LOOKUP_TYPE_MEMBERS_FIELDS.replace(
                        "__FIELD_PROJECTION__", field_projection.strip()
                    ),
                    {"project": project_name, "fqn": item_fqn, "limit": bounded_member_limit},
                )
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "types": types},
                types,
                limit=bounded_limit,
                total_count=total_count,
                extra=page_extra,
            ),
            output_format,
        )

    def code_lookup_methods(
        self,
        signature_fragment: str,
        project: str | None = None,
        skip: int = 0,
        limit: int = LOOKUP_LIMIT,
        include_tests: bool = False,
        compact: bool = True,
        include_count: bool = False,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        skip_value = _bounded_skip(skip)
        limit_value = _bounded_limit(limit, default=LOOKUP_LIMIT, maximum=200)
        # Split on whitespace for AND semantics: "GraphWriter upsertFile" matches methods whose
        # signature contains both terms rather than the exact joined string.
        fragment_terms = [t.strip().lower() for t
                          in (signature_fragment or "").split() if t.strip()]
        return_projection = (
            """
                   method.name AS name, method.ownerDisplayName AS ownerDisplayName,
                   method.startLine AS startLine, method.endLine AS endLine,
                   files, method.signature AS sortSignature
            """
            if compact
            else """
                   method.signature AS signature, method.name AS name,
                   method.ownerFqn AS ownerFqn, method.ownerDisplayName AS ownerDisplayName,
                   method.returnType AS returnType, method.visibility AS visibility,
                   method.startLine AS startLine, method.endLine AS endLine,
                   method.isStatic AS isStatic, method.isSynthetic AS isSynthetic, files
            """
        )
        # Rank methods whose owner exactly matches a fragment term first, so a query like
        # "ChunkEmbeddingRefresher" answers "methods of this class" on page 1 instead of
        # mixing in alphabetically earlier signatures that merely reference the class.
        owner_rank = "CASE WHEN toLower(ownerDisplayName) IN $fragment_terms THEN 0 ELSE 1 END"
        rows = self.client.run(
            Q.CODE_LOOKUP_METHODS
            .replace("__RETURN_PROJECTION__", return_projection.strip())
            .replace(
                "__ORDER_BY__",
                f"{owner_rank}, " + ("sortSignature" if compact else "signature"),
            ),
            {
                "project": project_name,
                "fragment_terms": fragment_terms,
                "skip": skip_value,
                "limit": _overfetch_limit(limit_value, include_count),
                "include_tests": include_tests,
            },
        )
        raw_rows = rows
        rows, page_extra = _trim_overfetch(
            rows,
            skip=skip_value,
            limit=limit_value,
            include_count=include_count,
        )
        # Owner-exact rows sort first, so once a non-exact row appears no exact row follows.
        # Tell paginating callers when the owner-exact rows are exhausted, so a query like
        # "ChunkEmbeddingRefresher" stops at page 1 instead of walking reference matches.
        if fragment_terms and page_extra:
            exact_flags = [
                (row.get("ownerDisplayName") or "").lower() in fragment_terms
                for row in raw_rows
            ]
            kept_exact = sum(exact_flags[: len(rows)])
            boundary_seen = not all(exact_flags)
            note = None
            if kept_exact and boundary_seen:
                note = (
                    "owner-exact matches end on this page; further rows only reference the "
                    "fragment — enumerate members via code_lookup_type(include_members=true)"
                )
            elif not kept_exact and skip_value:
                note = "no owner-exact matches on this page; rows only reference the fragment"
            if note:
                page_extra = {**page_extra, "note": note}
        if compact:
            rows = [
                {
                    "owner": row.get("ownerDisplayName"),
                    "name": row.get("name") or _method_name(row.get("signature")),
                    "path": _first(row.get("files")),
                    "startLine": row.get("startLine"),
                    "endLine": row.get("endLine"),
                }
                for row in rows
            ]
        total_count = None
        if include_count:
            count_rows = self.client.run(
                Q.CODE_LOOKUP_METHODS_COUNT,
                {
                    "project": project_name,
                    "fragment_terms": fragment_terms,
                    "include_tests": include_tests,
                },
            )
            total_count = count_rows[0].get("count", 0) if count_rows else len(rows)
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "methods": rows},
                rows,
                skip=skip_value,
                limit=limit_value,
                total_count=total_count,
                extra=page_extra,
            ),
            output_format,
        )

    def code_lookup_field(
        self,
        field_fragment: str,
        project: str | None = None,
        skip: int = 0,
        limit: int = LOOKUP_LIMIT,
        include_tests: bool = False,
        compact: bool = True,
        include_count: bool = False,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        skip_value = _bounded_skip(skip)
        limit_value = _bounded_limit(limit, default=LOOKUP_LIMIT, maximum=200)
        projection = (
            """
                   field.fqn AS fqn, field.name AS name,
                   coalesce(owner.ownerDisplayName, owner.name, owner.fqn) AS owner,
                   field.startLine AS startLine, field.endLine AS endLine,
                   files, field.fqn AS sortKey
            """
            if compact
            else """
                   field.fqn AS fqn, field.name AS name, field.type AS type,
                   field.visibility AS visibility, field.isStatic AS isStatic,
                   field.kind AS kind, field.language AS language,
                   owner.fqn AS ownerFqn,
                   coalesce(owner.ownerDisplayName, owner.name, owner.fqn) AS ownerDisplayName,
                   field.startLine AS startLine, field.endLine AS endLine, files
            """
        )
        rows = self.client.run(
            Q.CODE_LOOKUP_FIELD
            .replace("__PROJECTION__", projection.strip())
            .replace("__ORDER_BY__", "sortKey" if compact else "fqn"),
            {
                "project": project_name,
                "fragment": field_fragment,
                "skip": skip_value,
                "limit": _overfetch_limit(limit_value, include_count),
                "include_tests": include_tests,
            },
        )
        rows, page_extra = _trim_overfetch(
            rows,
            skip=skip_value,
            limit=limit_value,
            include_count=include_count,
        )
        if compact:
            rows = [
                {
                    "owner": row.get("owner"),
                    "name": row.get("name"),
                    "fqn": row.get("fqn"),
                    "path": _first(row.get("files")),
                    "startLine": row.get("startLine"),
                    "endLine": row.get("endLine"),
                }
                for row in rows
            ]
        total_count = None
        if include_count:
            count_rows = self.client.run(
                Q.CODE_LOOKUP_FIELD_COUNT,
                {
                    "project": project_name,
                    "fragment": field_fragment,
                    "include_tests": include_tests,
                },
            )
            total_count = count_rows[0].get("count", 0) if count_rows else len(rows)
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "fields": rows},
                rows,
                skip=skip_value,
                limit=limit_value,
                total_count=total_count,
                extra=page_extra,
            ),
            output_format,
        )

    def code_lookup_file(
        self,
        path_fragment: str,
        project: str | None = None,
        skip: int = 0,
        limit: int = LOOKUP_LIMIT,
        include_tests: bool = False,
        compact: bool = True,
        include_count: bool = False,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        skip_value = _bounded_skip(skip)
        limit_value = _bounded_limit(limit, default=LOOKUP_LIMIT, maximum=200)
        projection = (
            """
                   file.path AS path, file.language AS language,
                   definitionCount, chunkCount
            """
            if compact
            else """
                   file.path AS path, file.language AS language,
                   file.lastModified AS lastModified,
                   file.retainedSourceToken AS retainedSourceToken,
                   definitionCount, chunkCount
            """
        )
        rows = self.client.run(
            Q.CODE_LOOKUP_FILE.replace("__PROJECTION__", projection.strip()),
            {
                "project": project_name,
                "fragment": path_fragment,
                "skip": skip_value,
                "limit": _overfetch_limit(limit_value, include_count),
                "include_tests": include_tests,
            },
        )
        rows, page_extra = _trim_overfetch(
            rows,
            skip=skip_value,
            limit=limit_value,
            include_count=include_count,
        )
        total_count = None
        if include_count:
            count_rows = self.client.run(
                Q.CODE_LOOKUP_FILE_COUNT,
                {
                    "project": project_name,
                    "fragment": path_fragment,
                    "include_tests": include_tests,
                },
            )
            total_count = count_rows[0].get("count", 0) if count_rows else len(rows)
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "files": rows},
                rows,
                skip=skip_value,
                limit=limit_value,
                total_count=total_count,
                extra=page_extra,
            ),
            output_format,
        )
