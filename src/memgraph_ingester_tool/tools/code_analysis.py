"""Project-level analysis: orientation, hot paths, risk scans, quality stats, hierarchy, tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from memgraph_ingester_tool import queries as Q
from memgraph_ingester_tool.tools._base import MemgraphToolsBase
from memgraph_ingester_tool.tools._risk import (
    _aggregate_resource_risks,
    _normalize_extensions,
    _resource_risk_rows,
)
from memgraph_ingester_tool.tools._search_support import _test_fragment_parts
from memgraph_ingester_tool.tools._support import (
    DISCOVERY_LIMIT,
    _add_file_refs,
    _bounded_limit,
    _normalize_lower_list,
    _normalize_path_format,
    _normalize_sections,
    _replace_keys_with_ref,
    _with_result_meta,
)

HOT_PATH_SECTIONS = frozenset({"largestTypes", "longestMethods", "fanIn", "fanOut"})
DEFAULT_OPERATION_SINKS = frozenset(
    {
        "batch",
        "commit",
        "delete",
        "execute",
        "flush",
        "insert",
        "query",
        "read",
        "resolve",
        "run",
        "save",
        "update",
        "upsert",
        "write",
    }
)


class CodeAnalysisTools(MemgraphToolsBase):
    """Read-only analysis endpoints that aggregate over the whole project graph."""

    def code_orientation(
        self,
        project: str | None = None,
        limit: int = 30,
        sections: Sequence[str] | str | None = None,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        bounded_limit = _bounded_limit(limit, default=30, maximum=100)
        allowed_sections = frozenset({"languages", "packages", "largestTypes", "crossOwnerCalls"})
        requested = _normalize_sections(
            sections,
            allowed=allowed_sections,
            default=allowed_sections,
        )
        response: dict[str, Any] = {"project": project_name, "sections": sorted(requested)}
        if "languages" in requested:
            response["languages"] = self.client.run(
                Q.CODE_ORIENTATION_LANGUAGES,
                {"project": project_name},
            )
        if "packages" in requested:
            response["packages"] = self.client.run(
                Q.CODE_ORIENTATION_PACKAGES,
                {"project": project_name, "limit": bounded_limit},
            )
        if "largestTypes" in requested:
            response["largestTypes"] = self.client.run(
                Q.CODE_ORIENTATION_LARGEST_TYPES,
                {"project": project_name, "limit": bounded_limit},
            )
        if "crossOwnerCalls" in requested:
            response["crossOwnerCalls"] = self.client.run(
                Q.CODE_ORIENTATION_CROSS_OWNER_CALLS,
                {"project": project_name, "limit": bounded_limit},
            )
        return response

    def code_hot_paths(
        self,
        project: str | None = None,
        limit: int = DISCOVERY_LIMIT,
        include_tests: bool = False,
        include_evidence: bool = False,
        sections: Sequence[str] | str | None = None,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        bounded_limit = _bounded_limit(limit, default=DISCOVERY_LIMIT, maximum=50)
        requested_sections = _normalize_sections(
            sections,
            allowed=HOT_PATH_SECTIONS,
            default=frozenset({"fanIn", "longestMethods", "fanOut"}),
        )
        params = {
            "project": project_name,
            "limit": bounded_limit,
            "include_tests": include_tests,
        }
        largest_types = (
            self.client.run(Q.CODE_HOT_PATHS_LARGEST_TYPES, params)
            if "largestTypes" in requested_sections
            else []
        )
        longest_methods = (
            self.client.run(Q.CODE_HOT_PATHS_LONGEST_METHODS, params)
            if "longestMethods" in requested_sections
            else []
        )
        fan_in = (
            self.client.run(Q.CODE_HOT_PATHS_FAN_IN, params)
            if "fanIn" in requested_sections
            else []
        )
        fan_out = (
            self.client.run(Q.CODE_HOT_PATHS_FAN_OUT, params)
            if "fanOut" in requested_sections
            else []
        )
        rows: list[dict[str, Any]] = []
        for section, section_rows in (
            ("largestTypes", largest_types),
            ("longestMethods", longest_methods),
            ("fanIn", fan_in),
            ("fanOut", fan_out),
        ):
            for row in section_rows:
                row["section"] = section
                row.pop("sortKey", None)
                if not include_evidence:
                    row.pop("path", None)
                    row.pop("startLine", None)
                    row.pop("endLine", None)
                rows.append(row)
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "hotPaths": rows},
                rows,
                limit=bounded_limit,
            ),
            output_format,
        )

    def code_operation_hot_paths(
        self,
        project: str | None = None,
        sink_fragments: Sequence[str] | str | None = None,
        owner_fragment: str | None = None,
        path_contains: str | None = None,
        limit: int = DISCOVERY_LIMIT,
        include_tests: bool = False,
        output_format: str = "json",
        sink_limit: int = 3,
        include_all_sinks: bool = False,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        bounded_limit = _bounded_limit(limit, default=DISCOVERY_LIMIT, maximum=50)
        bounded_sink_limit = _bounded_limit(sink_limit, default=3, maximum=50)
        fragments = _normalize_lower_list(sink_fragments)
        custom_fragments = bool(fragments)
        fragments = fragments or sorted(DEFAULT_OPERATION_SINKS)
        owner_filter = (owner_fragment or "").strip().lower()
        path_filter = (path_contains or "").strip()
        rows = self.client.run(
            Q.CODE_OPERATION_HOT_PATHS,
            {
                "project": project_name,
                "fragments": fragments,
                "owner_fragment": owner_filter,
                "path_contains": path_filter,
                "include_tests": include_tests,
                "custom_fragments": custom_fragments,
                "limit": bounded_limit,
            },
        )
        for row in rows:
            row.pop("signature", None)
            row.pop("score", None)
            row.pop("lines", None)
            if not include_all_sinks and isinstance(row.get("sinks"), list):
                row["sinks"] = row["sinks"][:bounded_sink_limit]
            row["riskHints"] = [
                hint
                for hint, active in (
                    ("many-sink-calls", (row.get("sinkCallEdges") or 0) >= 5),
                    ("large-method", (row.get("endLine") or 0) - (row.get("startLine") or 0) >= 49),
                    ("multi-sink", (row.get("distinctSinks") or 0) >= 3),
                )
                if active
            ]
        extra: dict[str, Any] | None = None
        if owner_filter or path_filter:
            extra = {
                k: v
                for k, v in (
                    ("ownerFragment", owner_filter),
                    ("pathContains", path_filter),
                )
                if v
            }
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "operationHotPaths": rows},
                rows,
                limit=bounded_limit,
                extra=extra,
            ),
            output_format,
        )

    def code_resource_risk_scan(
        self,
        project: str | None = None,
        path_contains: str | None = None,
        extensions: Sequence[str] | str | None = None,
        limit: int = DISCOVERY_LIMIT,
        include_tests: bool = False,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        bounded_limit = _bounded_limit(limit, default=DISCOVERY_LIMIT, maximum=50)
        extension_filter = _normalize_extensions(extensions)
        path_filter = (path_contains or "").strip()
        candidate_limit = min(max(bounded_limit * 20, 100), 500)
        candidates = self.client.run(
            Q.CODE_RESOURCE_RISK_SCAN,
            {
                "project": project_name,
                "path_contains": path_filter,
                "include_tests": include_tests,
                "limit": candidate_limit,
            },
        )
        rows: list[dict[str, Any]] = []
        scanned_files = 0
        for candidate in candidates:
            path = candidate.get("path") or ""
            if extension_filter and not any(path.lower().endswith(ext) for ext in extension_filter):
                continue
            scanned_files += 1
            rows.extend(
                _resource_risk_rows(
                    path,
                    candidate.get("language"),
                    candidate.get("text") or "",
                )
            )
        rows = _aggregate_resource_risks(rows)
        rows.sort(
            key=lambda row: (
                -(row.get("score") or 0),
                row.get("path") or "",
                row.get("line") or 0,
                row.get("pattern") or "",
            )
        )
        rows = rows[:bounded_limit]
        return self._finalize_response(
            _with_result_meta(
                {"project": project_name, "resourceRisks": rows},
                rows,
                limit=bounded_limit,
            ),
            output_format,
        )

    def code_quality_stats(
        self,
        project: str | None = None,
        include_tests: bool = False,
        limit: int = DISCOVERY_LIMIT,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        bounded_limit = _bounded_limit(limit, default=DISCOVERY_LIMIT, maximum=50)
        params = {
            "project": project_name,
            "limit": bounded_limit,
            "include_tests": include_tests,
        }
        rows = self.client.run(Q.CODE_QUALITY_STATS, params)
        stats = rows[0] if rows else {}
        response = {
            "project": project_name,
            "inventory": stats.get("inventory", []),
            "methodLengths": stats.get("methodLengths", {}),
            "fanOut": stats.get("fanOut", {}),
            "fanIn": stats.get("fanIn", {}),
            "typeSizes": stats.get("typeSizes", {}),
            "chunksByLabel": stats.get("chunksByLabel", []),
            "filesByMethods": stats.get("filesByMethods", []),
        }
        response["meta"] = {"limit": bounded_limit}
        return self._finalize_response(response, output_format)

    def code_hierarchy(
        self,
        fqn: str,
        project: str | None = None,
        output_format: str = "json",
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        class_hierarchy = self.client.run(
            Q.CODE_HIERARCHY_CLASS,
            {"project": project_name, "fqn": fqn},
        )
        ancestors = self.client.run(
            Q.CODE_HIERARCHY_ANCESTORS,
            {"project": project_name, "fqn": fqn},
        )
        implementors = self.client.run(
            Q.CODE_HIERARCHY_IMPLEMENTORS,
            {"project": project_name, "fqn": fqn},
        )
        return self._finalize_response(
            {
                "project": project_name,
                "classHierarchy": class_hierarchy,
                "ancestors": ancestors,
                "interfaceImplementors": implementors,
            },
            output_format,
        )

    def code_test_context(
        self,
        test_fragment: str,
        project: str | None = None,
        limit: int = DISCOVERY_LIMIT,
        production_limit: int = DISCOVERY_LIMIT,
        output_format: str = "json",
        path_format: str | None = None,
    ) -> dict[str, Any]:
        project_name = self.resolve_project(project)
        normalized_path_format = _normalize_path_format(path_format, default="refs")
        bounded_limit = _bounded_limit(limit, default=DISCOVERY_LIMIT, maximum=25)
        bounded_production_limit = _bounded_limit(
            production_limit,
            default=DISCOVERY_LIMIT,
            maximum=50,
        )
        owner_fragment, _method_fragment, terms, min_term_matches = _test_fragment_parts(
            test_fragment,
        )
        rows = self.client.run(
            Q.CODE_TEST_METHODS,
            {
                "project": project_name,
                "fragment": test_fragment,
                "owner_fragment": owner_fragment,
                "terms": terms,
                "min_term_matches": min_term_matches,
                "limit": bounded_limit,
            },
        )
        file_rows = self.client.run(
            Q.CODE_TEST_FILES,
            {
                "project": project_name,
                "fragment": test_fragment,
                "owner_fragment": owner_fragment,
                "terms": terms,
                "min_term_matches": min_term_matches,
                "limit": bounded_limit,
            },
        )
        exact_matches = sum(1 for row in rows if row.get("exactish"))
        fuzzy_match_count = len(rows) - exact_matches
        rows = [row for row in rows if row.get("exactish")]
        production_rows = []
        if exact_matches > 0:
            production_rows = self.client.run(
                Q.CODE_TEST_PRODUCTION_CALLEES,
                {
                    "project": project_name,
                    "fragment": test_fragment,
                    "limit": bounded_production_limit,
                },
            )
        for row in rows:
            row.pop("signature", None)
            row.pop("exactish", None)
            row.pop("termMatches", None)
        production_rows = [r for r in production_rows if r.get("name") != "<init>"]
        for row in production_rows:
            row.pop("signature", None)
        meta: dict[str, Any] = {"exactMatches": exact_matches}
        if fuzzy_match_count:
            meta["fuzzyMatchesSuppressed"] = True
            meta["fuzzyMatchCount"] = fuzzy_match_count
        response = {
            "project": project_name,
            "tests": rows,
            "productionCallees": production_rows,
            "testFiles": file_rows,
            "meta": meta,
        }
        if normalized_path_format == "refs":
            _add_file_refs(response, ("tests", "productionCallees", "testFiles"))
            self._add_test_context_refs(response)
        return self._finalize_response(
            response,
            output_format,
        )

    def _add_test_context_refs(self, response: dict[str, Any]) -> None:
        tests = response.get("tests")
        production_callees = response.get("productionCallees")
        if not isinstance(tests, Sequence) or not isinstance(production_callees, Sequence):
            return

        test_index = {
            (test.get("owner"), test.get("name")): index
            for index, test in enumerate(tests)
            if isinstance(test, dict)
        }
        for row in production_callees:
            if not isinstance(row, dict):
                continue
            key = (row.get("testOwner"), row.get("testName"))
            if key not in test_index:
                continue
            _replace_keys_with_ref(
                row,
                first_key="testOwner",
                second_key="testName",
                ref_key="test",
                ref_value=test_index[key],
            )
