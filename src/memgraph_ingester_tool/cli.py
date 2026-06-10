"""argparse CLI that exposes every MemgraphTools endpoint as a subcommand.

Usage examples::

    mgtools server_status --project myproject
    mgtools code_search "auth filter" --project myproject --limit 5
    mgtools memory_orientation --project myproject --compact
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from memgraph_ingester_tool.config import ToolConfig
from memgraph_ingester_tool.db import ToolError
from memgraph_ingester_tool.tools import (
    CALL_GRAPH_LIMIT,
    DISCOVERY_LIMIT,
    LOOKUP_LIMIT,
    MEMBER_LIMIT,
    MemgraphTools,
)

# ── shared parent parser ──────────────────────────────────────────────────────

def _common_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--project", metavar="NAME", default=None,
                   help="Project name (overrides MEMGRAPH_TOOLS_PROJECT)")
    p.add_argument("--format", dest="output_format", metavar="FMT",
                   choices=["json", "table_json"], default="table_json",
                   help="Output format (default: table_json)")
    return p


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _print(result: Any) -> None:
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    print()


# ── subcommand definitions ────────────────────────────────────────────────────

def _register_server_status(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("server_status", parents=[common],
                       help="Graph inventory, memory counts, and vector indexes")
    p.set_defaults(cmd="server_status")


def _register_code_orientation(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_orientation", parents=[common],
                       help="Compact code graph overview")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--sections", type=_csv, default=None,
                   metavar="S1,S2",
                   help="languages,packages,largestTypes,crossOwnerCalls")
    p.set_defaults(cmd="code_orientation")


def _register_code_search(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_search", parents=[common],
                       help="Hybrid vector+lexical CodeChunk search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=DISCOVERY_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--include-text", action="store_true")
    p.add_argument("--text-limit", type=int, default=160)
    p.add_argument("--kinds", type=_csv, default=None)
    p.add_argument("--path-prefixes", type=_csv, default=None)
    p.add_argument("--path-contains", default=None)
    p.add_argument("--owner-fragment", default=None)
    p.add_argument("--min-score", type=float, default=0.0)
    p.add_argument("--include-secondary", action="store_true")
    p.add_argument("--rag-roles", type=_csv, default=None)
    p.set_defaults(cmd="code_search")


def _register_code_text_search(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_text_search", parents=[common],
                       help="Lexical search over indexed chunk text")
    p.add_argument("--query", default=None)
    p.add_argument("--all-terms", type=_csv, default=None, metavar="T1,T2")
    p.add_argument("--any-terms", type=_csv, default=None, metavar="T1,T2")
    p.add_argument("--limit", type=int, default=DISCOVERY_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--include-text", action="store_true")
    p.add_argument("--text-limit", type=int, default=160)
    p.add_argument("--kinds", type=_csv, default=None)
    p.add_argument("--include-secondary", action="store_true")
    p.add_argument("--rag-roles", type=_csv, default=None)
    p.add_argument("--path-contains", default=None)
    p.set_defaults(cmd="code_text_search")


def _register_code_discovery_context(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_discovery_context", parents=[common],
                       help="Top anchors plus bounded exact/call/file context")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--neighbor-limit", type=int, default=3)
    p.set_defaults(cmd="code_discovery_context")


def _register_code_file_context(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_file_context", parents=[common],
                       help="Compact file outlines with top symbols")
    p.add_argument("fragments", nargs="+", help="One or more path fragments")
    p.add_argument("--limit-files", type=int, default=5)
    p.add_argument("--symbol-limit", type=int, default=8)
    p.add_argument("--include-tests", action="store_true")
    p.set_defaults(cmd="code_file_context")


def _register_code_flow_context(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_flow_context", parents=[common],
                       help="Semantic+lexical anchors, outlines, and call edges")
    p.add_argument("query")
    p.add_argument("--limit-files", type=int, default=3)
    p.add_argument("--anchor-limit", type=int, default=3)
    p.add_argument("--symbol-limit", type=int, default=3)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--detail", choices=["compact", "full"], default="compact")
    p.set_defaults(cmd="code_flow_context")


def _register_code_lookup_type(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_lookup_type", parents=[common],
                       help="Look up types by name or FQN")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--type-name", default=None)
    group.add_argument("--fqn", default=None)
    p.add_argument("--include-members", action="store_true")
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--member-limit", type=int, default=MEMBER_LIMIT)
    p.add_argument("--member-summary", action="store_true")
    p.add_argument("--limit", type=int, default=LOOKUP_LIMIT)
    p.add_argument("--compact", type=_bool, default=True)
    p.set_defaults(cmd="code_lookup_type")


def _register_code_lookup_methods(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_lookup_methods", parents=[common],
                       help="Find methods by signature fragment")
    p.add_argument("signature_fragment")
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("--limit", type=int, default=LOOKUP_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--compact", type=_bool, default=True)
    p.add_argument("--include-count", action="store_true")
    p.set_defaults(cmd="code_lookup_methods")


def _register_code_lookup_field(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_lookup_field", parents=[common],
                       help="Find fields by FQN or name fragment")
    p.add_argument("field_fragment")
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("--limit", type=int, default=LOOKUP_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--compact", type=_bool, default=True)
    p.add_argument("--include-count", action="store_true")
    p.set_defaults(cmd="code_lookup_field")


def _register_code_lookup_file(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_lookup_file", parents=[common],
                       help="Find indexed files by path fragment")
    p.add_argument("path_fragment")
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("--limit", type=int, default=LOOKUP_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--compact", type=_bool, default=True)
    p.add_argument("--include-count", action="store_true")
    p.set_defaults(cmd="code_lookup_file")


def _register_code_impact(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_impact", parents=[common],
                       help="Refactor blast-radius for matching methods")
    p.add_argument("signature_fragment")
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("--limit", type=int, default=CALL_GRAPH_LIMIT)
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--include-tests", type=_bool, default=True)
    p.add_argument("--compact", type=_bool, default=True)
    p.add_argument("--view", choices=["callers", "files"], default="callers")
    p.set_defaults(cmd="code_impact")


def _register_code_callers(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_callers", parents=[common],
                       help="List callers of matching callee signatures")
    p.add_argument("callee_fragment")
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("--limit", type=int, default=CALL_GRAPH_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--compact", type=_bool, default=True)
    p.add_argument("--include-count", action="store_true")
    p.set_defaults(cmd="code_callers")


def _register_code_method_context(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_method_context", parents=[common],
                       help="Method lookup plus compact caller and callee context")
    p.add_argument("signature_fragment")
    p.add_argument("--method-limit", type=int, default=DISCOVERY_LIMIT)
    p.add_argument("--neighbor-limit", type=int, default=DISCOVERY_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--compact", type=_bool, default=True)
    p.set_defaults(cmd="code_method_context")


def _register_code_callees(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_callees", parents=[common],
                       help="List callees of matching caller signatures")
    p.add_argument("caller_fragment")
    p.add_argument("--skip", type=int, default=0)
    p.add_argument("--limit", type=int, default=CALL_GRAPH_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--compact", type=_bool, default=True)
    p.add_argument("--include-count", action="store_true")
    p.set_defaults(cmd="code_callees")


def _register_code_hot_paths(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_hot_paths", parents=[common],
                       help="Hot-path candidates by size, fan-in, and fan-out")
    p.add_argument("--limit", type=int, default=DISCOVERY_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--include-evidence", action="store_true")
    p.add_argument("--sections", type=_csv, default=None,
                   metavar="S1,S2",
                   help="largestTypes,longestMethods,fanIn,fanOut")
    p.set_defaults(cmd="code_hot_paths")


def _register_code_operation_hot_paths(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_operation_hot_paths", parents=[common],
                       help="Methods with many calls to operation-like sinks")
    p.add_argument("--sink-fragments", type=_csv, default=None)
    p.add_argument("--owner-fragment", default=None)
    p.add_argument("--path-contains", default=None)
    p.add_argument("--limit", type=int, default=DISCOVERY_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.set_defaults(cmd="code_operation_hot_paths")


def _register_code_resource_risk_scan(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_resource_risk_scan", parents=[common],
                       help="Heuristic risks in query/config/resource files")
    p.add_argument("--path-contains", default=None)
    p.add_argument("--extensions", type=_csv, default=None)
    p.add_argument("--limit", type=int, default=DISCOVERY_LIMIT)
    p.add_argument("--include-tests", action="store_true")
    p.set_defaults(cmd="code_resource_risk_scan")


def _register_code_quality_stats(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_quality_stats", parents=[common],
                       help="Graph-wide code quality and quantity metrics")
    p.add_argument("--include-tests", action="store_true")
    p.add_argument("--limit", type=int, default=DISCOVERY_LIMIT)
    p.set_defaults(cmd="code_quality_stats")


def _register_code_hierarchy(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_hierarchy", parents=[common],
                       help="Class ancestry, children, interfaces, and implementors")
    p.add_argument("fqn")
    p.set_defaults(cmd="code_hierarchy")


def _register_code_test_context(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("code_test_context", parents=[common],
                       help="Matching tests and production callees for CI triage")
    p.add_argument("test_fragment")
    p.add_argument("--limit", type=int, default=DISCOVERY_LIMIT)
    p.add_argument("--production-limit", type=int, default=DISCOVERY_LIMIT)
    p.set_defaults(cmd="code_test_context")


def _register_raw_read_cypher(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("raw_read_cypher", parents=[common],
                       help="Project-scoped read-only Cypher escape hatch")
    p.add_argument("query")
    p.add_argument("--parameters", type=json.loads, default=None,
                   metavar="JSON", help="Query parameters as a JSON object")
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(cmd="raw_read_cypher")


def _register_memory_orientation(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("memory_orientation", parents=[common],
                       help="Rules plus open findings, tasks, questions, and risks")
    p.add_argument("--compact", action="store_true")
    p.set_defaults(cmd="memory_orientation")


def _register_memory_schema(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("memory_schema", parents=[common],
                       help="Memory types, fields, controlled values, and CodeRef targets")
    p.add_argument("--memory-type", default=None)
    p.set_defaults(cmd="memory_schema")


def _register_memory_search(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("memory_search", parents=[common],
                       help="Search MemoryChunk embeddings")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(cmd="memory_search")


def _register_memory_get(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("memory_get", parents=[common],
                       help="Fetch one canonical memory node")
    p.add_argument("memory_id")
    p.set_defaults(cmd="memory_get")


def _register_delete_memory(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("delete_memory", parents=[common],
                       help="Delete one Memory node plus its chunk and orphan CodeRefs")
    p.add_argument("memory_id")
    p.set_defaults(cmd="delete_memory")


def _register_memory_upsert(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("memory_upsert", parents=[common],
                       help="Create or update a Memory node")
    p.add_argument("memory_type")
    p.add_argument("memory_id")
    p.add_argument("fields", type=json.loads, metavar="FIELDS_JSON",
                   help="Memory fields as a JSON object")
    p.add_argument("--code-ref", type=json.loads, default=None,
                   metavar="JSON", help='{"target_type":"Method","key":"..."}')
    p.add_argument("--no-refresh-chunk", dest="refresh_chunk", action="store_false")
    p.add_argument("--no-embed", dest="embed", action="store_false")
    p.set_defaults(cmd="memory_upsert", refresh_chunk=True, embed=True)


def _register_memory_update_status(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("memory_update_status", parents=[common],
                       help="Update a lifecycle status")
    p.add_argument("memory_type")
    p.add_argument("memory_id")
    p.add_argument("status")
    p.add_argument("--no-refresh-chunk", dest="refresh_chunk", action="store_false")
    p.add_argument("--no-embed", dest="embed", action="store_false")
    p.set_defaults(cmd="memory_update_status", refresh_chunk=True, embed=True)


def _register_memory_link_code_ref(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("memory_link_code_ref", parents=[common],
                       help="Link a Memory node to a CodeRef target")
    p.add_argument("memory_type")
    p.add_argument("memory_id")
    p.add_argument("target_type")
    p.add_argument("key")
    p.add_argument("--no-refresh-chunk", dest="refresh_chunk", action="store_false")
    p.add_argument("--no-embed", dest="embed", action="store_false")
    p.set_defaults(cmd="memory_link_code_ref", refresh_chunk=True, embed=True)


def _register_memory_refresh_chunk(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("memory_refresh_chunk", parents=[common],
                       help="Rebuild one derived MemoryChunk")
    p.add_argument("memory_type")
    p.add_argument("memory_id")
    p.add_argument("--no-embed", dest="embed", action="store_false")
    p.set_defaults(cmd="memory_refresh_chunk", embed=True)


def _register_memory_refresh_embeddings(sub: Any, common: argparse.ArgumentParser) -> None:
    p = sub.add_parser("memory_refresh_embeddings", parents=[common],
                       help="Refresh embeddings for selected MemoryChunk ids")
    p.add_argument("chunk_ids", nargs="+")
    p.set_defaults(cmd="memory_refresh_embeddings")


# ── dispatch ──────────────────────────────────────────────────────────────────


def _dispatch(tools: MemgraphTools, args: argparse.Namespace) -> Any:
    cmd = args.cmd
    fmt = args.output_format
    project = args.project

    match cmd:
        case "server_status":
            return tools.server_status(project)
        case "code_orientation":
            return tools.code_orientation(project, args.limit, args.sections)
        case "code_search":
            return tools.code_search(
                args.query, project, args.limit,
                include_tests=args.include_tests,
                include_text=args.include_text,
                text_limit=args.text_limit,
                kinds=args.kinds,
                path_prefixes=args.path_prefixes,
                path_contains=args.path_contains,
                owner_fragment=args.owner_fragment,
                min_score=args.min_score,
                include_secondary=args.include_secondary,
                rag_roles=args.rag_roles,
                output_format=fmt,
            )
        case "code_text_search":
            return tools.code_text_search(
                query=args.query,
                project=project,
                all_terms=args.all_terms,
                any_terms=args.any_terms,
                limit=args.limit,
                include_tests=args.include_tests,
                include_text=args.include_text,
                text_limit=args.text_limit,
                kinds=args.kinds,
                include_secondary=args.include_secondary,
                rag_roles=args.rag_roles,
                path_contains=args.path_contains,
                output_format=fmt,
            )
        case "code_discovery_context":
            return tools.code_discovery_context(
                args.query, project, args.limit,
                include_tests=args.include_tests,
                neighbor_limit=args.neighbor_limit,
                output_format=fmt,
            )
        case "code_file_context":
            return tools.code_file_context(
                args.fragments, project,
                limit_files=args.limit_files,
                symbol_limit=args.symbol_limit,
                include_tests=args.include_tests,
                output_format=fmt,
            )
        case "code_flow_context":
            return tools.code_flow_context(
                args.query, project,
                limit_files=args.limit_files,
                anchor_limit=args.anchor_limit,
                symbol_limit=args.symbol_limit,
                include_tests=args.include_tests,
                detail=args.detail,
                output_format=fmt,
            )
        case "code_lookup_type":
            return tools.code_lookup_type(
                project=project,
                type_name=args.type_name,
                fqn=args.fqn,
                include_members=args.include_members,
                include_tests=args.include_tests,
                member_limit=args.member_limit,
                member_summary=args.member_summary,
                limit=args.limit,
                compact=args.compact,
                output_format=fmt,
            )
        case "code_lookup_methods":
            return tools.code_lookup_methods(
                args.signature_fragment, project,
                skip=args.skip, limit=args.limit,
                include_tests=args.include_tests,
                compact=args.compact,
                include_count=args.include_count,
                output_format=fmt,
            )
        case "code_lookup_field":
            return tools.code_lookup_field(
                args.field_fragment, project,
                skip=args.skip, limit=args.limit,
                include_tests=args.include_tests,
                compact=args.compact,
                include_count=args.include_count,
                output_format=fmt,
            )
        case "code_lookup_file":
            return tools.code_lookup_file(
                args.path_fragment, project,
                skip=args.skip, limit=args.limit,
                include_tests=args.include_tests,
                compact=args.compact,
                include_count=args.include_count,
                output_format=fmt,
            )
        case "code_impact":
            return tools.code_impact(
                args.signature_fragment, project,
                skip=args.skip, limit=args.limit, depth=args.depth,
                include_tests=args.include_tests,
                compact=args.compact, view=args.view,
                output_format=fmt,
            )
        case "code_callers":
            return tools.code_callers(
                args.callee_fragment, project,
                skip=args.skip, limit=args.limit,
                include_tests=args.include_tests,
                compact=args.compact,
                include_count=args.include_count,
                output_format=fmt,
            )
        case "code_method_context":
            return tools.code_method_context(
                args.signature_fragment, project,
                method_limit=args.method_limit,
                neighbor_limit=args.neighbor_limit,
                include_tests=args.include_tests,
                compact=args.compact,
                output_format=fmt,
            )
        case "code_callees":
            return tools.code_callees(
                args.caller_fragment, project,
                skip=args.skip, limit=args.limit,
                include_tests=args.include_tests,
                compact=args.compact,
                include_count=args.include_count,
                output_format=fmt,
            )
        case "code_hot_paths":
            return tools.code_hot_paths(
                project, limit=args.limit,
                include_tests=args.include_tests,
                include_evidence=args.include_evidence,
                sections=args.sections,
                output_format=fmt,
            )
        case "code_operation_hot_paths":
            return tools.code_operation_hot_paths(
                project,
                sink_fragments=args.sink_fragments,
                owner_fragment=args.owner_fragment,
                path_contains=args.path_contains,
                limit=args.limit,
                include_tests=args.include_tests,
                output_format=fmt,
            )
        case "code_resource_risk_scan":
            return tools.code_resource_risk_scan(
                project,
                path_contains=args.path_contains,
                extensions=args.extensions,
                limit=args.limit,
                include_tests=args.include_tests,
                output_format=fmt,
            )
        case "code_quality_stats":
            return tools.code_quality_stats(
                project,
                include_tests=args.include_tests,
                limit=args.limit,
                output_format=fmt,
            )
        case "code_hierarchy":
            return tools.code_hierarchy(args.fqn, project, output_format=fmt)
        case "code_test_context":
            return tools.code_test_context(
                args.test_fragment, project,
                limit=args.limit,
                production_limit=args.production_limit,
                output_format=fmt,
            )
        case "raw_read_cypher":
            return tools.raw_read_cypher(
                args.query, project,
                parameters=args.parameters,
                limit=args.limit,
                output_format=fmt,
            )
        case "memory_orientation":
            return tools.memory_orientation(project, compact=args.compact)
        case "memory_schema":
            return tools.memory_schema(args.memory_type)
        case "memory_search":
            return tools.memory_search(args.query, project, args.limit)
        case "memory_get":
            return tools.memory_get(args.memory_id, project)
        case "delete_memory":
            return tools.delete_memory(args.memory_id, project)
        case "memory_upsert":
            return tools.memory_upsert(
                args.memory_type, args.memory_id, args.fields, project,
                code_ref=args.code_ref,
                refresh_chunk=args.refresh_chunk,
                embed=args.embed,
            )
        case "memory_update_status":
            return tools.memory_update_status(
                args.memory_type, args.memory_id, args.status, project,
                refresh_chunk=args.refresh_chunk,
                embed=args.embed,
            )
        case "memory_link_code_ref":
            return tools.memory_link_code_ref(
                args.memory_type, args.memory_id,
                args.target_type, args.key, project,
                refresh_chunk=args.refresh_chunk,
                embed=args.embed,
            )
        case "memory_refresh_chunk":
            return tools.memory_refresh_chunk(
                args.memory_type, args.memory_id, project, embed=args.embed
            )
        case "memory_refresh_embeddings":
            return tools.memory_refresh_embeddings(args.chunk_ids, project)
        case _:
            raise SystemExit(f"Unknown command: {cmd!r}")


# ── entry point ───────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    common = _common_parser()
    root = argparse.ArgumentParser(
        prog="mgtools",
        description="Standalone CLI for Memgraph knowledge graph tools.",
    )
    sub = root.add_subparsers(dest="cmd", metavar="COMMAND", required=True)

    for register in (
        _register_server_status,
        _register_code_orientation,
        _register_code_search,
        _register_code_text_search,
        _register_code_discovery_context,
        _register_code_file_context,
        _register_code_flow_context,
        _register_code_lookup_type,
        _register_code_lookup_methods,
        _register_code_lookup_field,
        _register_code_lookup_file,
        _register_code_impact,
        _register_code_callers,
        _register_code_method_context,
        _register_code_callees,
        _register_code_hot_paths,
        _register_code_operation_hot_paths,
        _register_code_resource_risk_scan,
        _register_code_quality_stats,
        _register_code_hierarchy,
        _register_code_test_context,
        _register_raw_read_cypher,
        _register_memory_orientation,
        _register_memory_schema,
        _register_memory_search,
        _register_memory_get,
        _register_delete_memory,
        _register_memory_upsert,
        _register_memory_update_status,
        _register_memory_link_code_ref,
        _register_memory_refresh_chunk,
        _register_memory_refresh_embeddings,
    ):
        register(sub, common)

    return root


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    config = ToolConfig.from_environment()
    if args.project:
        config = ToolConfig(
            bolt_uri=config.bolt_uri,
            username=config.username,
            password=config.password,
            database=config.database,
            default_project=args.project,
            query_timeout_seconds=config.query_timeout_seconds,
            read_only=config.read_only,
            code_embedding_index_name=config.code_embedding_index_name,
            memory_embedding_index_name=config.memory_embedding_index_name,
            embedding_model_name=config.embedding_model_name,
            embedding_dimensions=config.embedding_dimensions,
        )
    tools = MemgraphTools(config)
    try:
        result = _dispatch(tools, args)
        _print(result)
    except ToolError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
