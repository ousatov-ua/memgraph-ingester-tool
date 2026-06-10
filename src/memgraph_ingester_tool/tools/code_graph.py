"""Call-graph navigation: impact analysis, callers, callees, method context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from memgraph_ingester_tool import queries as Q
from memgraph_ingester_tool.db import ToolError
from memgraph_ingester_tool.tools._support import (
    CALL_GRAPH_LIMIT,
    DISCOVERY_LIMIT,
    _bounded_depth,
    _bounded_limit,
    _bounded_skip,
    _first,
    _is_test_path,
    _method_name,
    _overfetch_limit,
    _package_name,
    _trim_overfetch,
    _with_result_meta,
)
from memgraph_ingester_tool.tools.code_lookup import CodeLookupTools


class CodeGraphTools(CodeLookupTools):
    """code_impact / code_callers / code_callees / code_method_context."""

    def code_impact(
        self,
        signature_fragment: str,
        project: str | None = None,
        skip: int = 0,
        limit: int = CALL_GRAPH_LIMIT,
        depth: int = 2,
        include_tests: bool = True,
        compact: bool = True,
        view: str = "callers",
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        if view not in {"callers", "files"}:
            raise ToolError("code_impact view must be 'callers' or 'files'.")
        skip_value = _bounded_skip(skip)
        limit_value = _bounded_limit(limit, default=CALL_GRAPH_LIMIT, maximum=200)
        depth_value = _bounded_depth(depth)
        params = {
            "project": project_name,
            "fragment": signature_fragment,
            "skip": skip_value,
            "limit": limit_value,
            "impact_limit": limit_value + 1,
            "depth": depth_value,
            "include_tests": include_tests,
        }
        target_rows = self.client.run(Q.CODE_IMPACT_TARGETS, params)
        impact_rows = self.client.run(Q.CODE_IMPACT_CALLERS, params)
        impact_rows, result_meta_extra = _trim_overfetch(
            impact_rows,
            skip=skip_value,
            limit=limit_value,
            include_count=False,
        )
        if not impact_rows and target_rows:
            fallback_rows = self._code_impact_text_reference_rows(
                params,
                target_rows,
                skip=skip_value,
                limit=limit_value,
            )
            impact_rows, fallback_page_extra = _trim_overfetch(
                fallback_rows,
                skip=skip_value,
                limit=limit_value,
                include_count=False,
            )
            if impact_rows:
                result_meta_extra = {"inference": "textReference"}
                if fallback_page_extra:
                    result_meta_extra.update(fallback_page_extra)

        targets = [
            {
                "owner": row.get("owner"),
                "name": row.get("name") or _method_name(row.get("signature")),
                "signature": row.get("signature"),
                "path": _first(row.get("files")),
                "startLine": row.get("startLine"),
                "endLine": row.get("endLine"),
            }
            if compact
            else row
            for row in target_rows
        ]
        impacts = [self._format_impact_row(row, compact) for row in impact_rows]
        if view == "files":
            file_rows = self._impact_file_rows(targets, impacts)
            file_meta_extra = (
                {"inference": result_meta_extra["inference"]}
                if result_meta_extra and "inference" in result_meta_extra
                else None
            )
            return self._finalize_response(
                _with_result_meta(
                    {
                        "project": project_name,
                        "targetMethods": targets,
                        "files": file_rows,
                    },
                    file_rows,
                    skip=0,
                    limit=limit_value,
                    total_count=len(file_rows),
                    extra=file_meta_extra,
                ),
                output_format,
            )
        return self._finalize_response(
            _with_result_meta(
                {
                    "project": project_name,
                    "targetMethods": targets,
                    "impacts": impacts,
                },
                impacts,
                skip=skip_value,
                limit=limit_value,
                extra=result_meta_extra,
            ),
            output_format,
        )

    def _code_impact_text_reference_rows(
        self,
        params: Mapping[str, Any],
        target_rows: Sequence[Mapping[str, Any]],
        *,
        skip: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        target_names = sorted(
            {
                name
                for row in target_rows
                if (name := (row.get("name") or _method_name(row.get("signature"))))
                and len(name) >= 4
            }
        )
        target_signatures = sorted(
            {signature for row in target_rows if (signature := row.get("signature"))}
        )
        if not target_names or not target_signatures:
            return []
        target_terms = [term for name in target_names for term in (f"{name}(", f"{name} (")]
        return self.client.run(
            Q.CODE_IMPACT_TEXT_REFERENCE,
            {
                **params,
                "target_signatures": target_signatures,
                "target_terms": target_terms,
                "skip": skip,
                "fallback_limit": limit + 1,
            },
        )

    def _impact_file_rows(
        self,
        targets: Sequence[dict[str, Any]],
        impacts: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_path: dict[str, dict[str, Any]] = {}
        for target in targets:
            path = target.get("path")
            if not path:
                continue
            by_path[path] = {
                "path": path,
                "role": "target",
                "minDepth": 0,
                "callerCount": 0,
                "testCallerCount": 0,
                "crossPackageCount": 0,
                "risk": "high",
            }
        for impact in impacts:
            path = impact.get("path")
            if not path:
                continue
            row = by_path.setdefault(
                path,
                {
                    "path": path,
                    "role": "caller",
                    "minDepth": impact.get("depth"),
                    "callerCount": 0,
                    "testCallerCount": 0,
                    "crossPackageCount": 0,
                    "risk": "low",
                },
            )
            row["minDepth"] = min(row.get("minDepth") or impact.get("depth"), impact.get("depth"))
            row["callerCount"] += 1
            if impact.get("isTest"):
                row["testCallerCount"] += 1
            if impact.get("crossesPackageBoundary"):
                row["crossPackageCount"] += 1
            if row["role"] != "target":
                if row["minDepth"] == 1 and not impact.get("isTest"):
                    row["risk"] = "high"
                elif row["risk"] != "high" and (row["minDepth"] == 1 or impact.get("isTest")):
                    row["risk"] = "medium"
        return sorted(
            by_path.values(),
            key=lambda row: (
                {"high": 0, "medium": 1, "low": 2}.get(row.get("risk"), 3),
                row.get("minDepth") or 99,
                row.get("path") or "",
            ),
        )

    def _format_impact_row(self, row: dict[str, Any], compact: bool) -> dict[str, Any]:
        caller_path = row.get("callerPath")
        caller_package = _package_name(row.get("callerOwnerFqn"))
        target_package = _package_name(row.get("targetOwnerFqn"))
        enriched = dict(row)
        enriched["isTest"] = _is_test_path(caller_path)
        crosses_pkg = (
            caller_package != target_package if caller_package and target_package else None
        )
        enriched["crossesPackageBoundary"] = crosses_pkg
        if not compact:
            return enriched
        return {
            "depth": enriched.get("depth"),
            "owner": enriched.get("callerOwner"),
            "name": enriched.get("callerName") or _method_name(enriched.get("callerSignature")),
            "path": caller_path,
            "startLine": enriched.get("callerStartLine"),
            "endLine": enriched.get("callerEndLine"),
            "viaOwner": enriched.get("viaOwner"),
            "viaName": enriched.get("viaName") or _method_name(enriched.get("viaSignature")),
            "targetOwner": enriched.get("targetOwner"),
            "targetName": enriched.get("targetName")
            or _method_name(enriched.get("targetSignature")),
            "isTest": enriched.get("isTest"),
            "crossesPackageBoundary": crosses_pkg,
            "inferred": enriched.get("inferred"),
            "evidence": enriched.get("evidence"),
        }

    def code_callers(
        self,
        callee_fragment: str,
        project: str | None = None,
        skip: int = 0,
        limit: int = CALL_GRAPH_LIMIT,
        include_tests: bool = False,
        compact: bool = True,
        include_count: bool = False,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        skip_value = _bounded_skip(skip)
        limit_value = _bounded_limit(limit, default=CALL_GRAPH_LIMIT, maximum=100)
        rows = self.client.run(
            Q.CODE_CALLERS,
            {
                "project": project_name,
                "fragment": callee_fragment,
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
                Q.CODE_CALLERS_COUNT,
                {
                    "project": project_name,
                    "fragment": callee_fragment,
                    "include_tests": include_tests,
                },
            )
            total_count = count_rows[0].get("count", 0) if count_rows else len(rows)
        if compact:
            rows = [
                {
                    "owner": row.get("callerOwner"),
                    "name": row.get("callerName") or _method_name(row.get("callerSignature")),
                    "path": row.get("callerPath"),
                    "startLine": row.get("callerStartLine"),
                    "endLine": row.get("callerEndLine"),
                    "calleeOwner": row.get("calleeOwner"),
                    "calleeName": row.get("calleeName") or _method_name(row.get("calleeSignature")),
                }
                for row in rows
            ]
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "callers": rows},
                rows,
                skip=skip_value,
                limit=limit_value,
                total_count=total_count,
                extra=page_extra,
            ),
            output_format,
        )

    def code_method_context(
        self,
        signature_fragment: str,
        project: str | None = None,
        method_limit: int = DISCOVERY_LIMIT,
        neighbor_limit: int = DISCOVERY_LIMIT,
        include_tests: bool = False,
        compact: bool = True,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        methods = self.code_lookup_methods(
            signature_fragment,
            project_name,
            skip=0,
            limit=method_limit,
            include_tests=include_tests,
            compact=compact,
            output_format="json",
        )
        callers = self.code_callers(
            signature_fragment,
            project_name,
            skip=0,
            limit=neighbor_limit,
            include_tests=include_tests,
            compact=compact,
            output_format="json",
        )
        callees = self.code_callees(
            signature_fragment,
            project_name,
            skip=0,
            limit=neighbor_limit,
            include_tests=include_tests,
            compact=compact,
            output_format="json",
        )
        return self._finalize_response(
            {
                "project": project_name,
                "methods": methods["methods"],
                "callers": callers["callers"],
                "callees": callees["callees"],
                "meta": {
                    "methods": methods["meta"],
                    "callers": callers["meta"],
                    "callees": callees["meta"],
                },
            },
            output_format,
        )

    def code_callees(
        self,
        caller_fragment: str,
        project: str | None = None,
        skip: int = 0,
        limit: int = CALL_GRAPH_LIMIT,
        include_tests: bool = False,
        compact: bool = True,
        include_count: bool = False,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        skip_value = _bounded_skip(skip)
        limit_value = _bounded_limit(limit, default=CALL_GRAPH_LIMIT, maximum=100)
        rows = self.client.run(
            Q.CODE_CALLEES,
            {
                "project": project_name,
                "fragment": caller_fragment,
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
                Q.CODE_CALLEES_COUNT,
                {
                    "project": project_name,
                    "fragment": caller_fragment,
                    "include_tests": include_tests,
                },
            )
            total_count = count_rows[0].get("count", 0) if count_rows else len(rows)
        if compact:
            rows = [
                {
                    "callerOwner": row.get("callerOwner"),
                    "callerName": row.get("callerName") or _method_name(row.get("callerSignature")),
                    "owner": row.get("calleeOwner"),
                    "name": row.get("calleeName") or _method_name(row.get("calleeSignature")),
                    "path": row.get("calleePath"),
                    "startLine": row.get("calleeStartLine"),
                    "endLine": row.get("calleeEndLine"),
                }
                for row in rows
            ]
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "callees": rows},
                rows,
                skip=skip_value,
                limit=limit_value,
                total_count=total_count,
                extra=page_extra,
            ),
            output_format,
        )
