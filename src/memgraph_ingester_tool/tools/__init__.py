"""High-level Memgraph query tools — the single source of truth.

Public methods on :class:`MemgraphTools` mirror every MCP endpoint exactly so
that MCP users and mgconsole/CLI users share one implementation.

The implementation is split into focused mixins (search, lookup, call graph,
analysis, context, memory) over a shared :class:`MemgraphToolsBase`; every
name historically importable from ``memgraph_ingester_tool.tools`` is
re-exported here so the module contract is unchanged.
"""

from __future__ import annotations

from memgraph_ingester_tool.config import ToolConfig
from memgraph_ingester_tool.db import ToolClient, ToolError
from memgraph_ingester_tool.schema import (
    MEMORY_SPECS,
    READ_ONLY_PREFIXES,
    TARGET_TYPES,
    WRITE_KEYWORDS,
)
from memgraph_ingester_tool.tools._guards import (
    STRING_RE,
    TOKEN_RE,
    _ensure_project_scoped,
    _ensure_read_only_query,
    _strip_strings,
)
from memgraph_ingester_tool.tools._memory_support import (
    CONTROLLED_VALUES,
    MEMORY_CHUNK_EXCLUDED_PROPERTIES,
    _memory_label_predicate,
    _memory_schema_entry,
    _memory_spec,
    _target_match,
    _validate_target_type,
)
from memgraph_ingester_tool.tools._risk import (
    RESOURCE_SCAN_EXTENSIONS,
    ROOT_MATCH_RE,
    SQL_WRITE_WITHOUT_WHERE_RE,
    UNBOUNDED_GRAPH_TRAVERSAL_RE,
    _aggregate_resource_risks,
    _normalize_extensions,
    _resource_risk_rows,
    _source_excerpt,
)
from memgraph_ingester_tool.tools._search_support import (
    AUTO_QUERY_STOPWORDS,
    CAMEL_BOUNDARY_RE,
    DEFAULT_RAG_ROLES,
    LEXICAL_RRF_WEIGHT,
    RRF_K,
    _dedupe_chunk_rows,
    _identifier_terms,
    _lexical_query_terms,
    _passes_chunk_filters,
    _query_variants,
    _rrf_fuse,
    _test_fragment_parts,
)
from memgraph_ingester_tool.tools._support import (
    CALL_GRAPH_LIMIT,
    DISCOVERY_LIMIT,
    LOOKUP_LIMIT,
    MEMBER_LIMIT,
    OUTPUT_FORMATS,
    _bounded_depth,
    _bounded_limit,
    _bounded_skip,
    _bounded_symbol_limit,
    _bounded_text_limit,
    _compact_owner,
    _compact_text,
    _contains_any,
    _first,
    _format_response,
    _fragment_rank,
    _group_limited,
    _is_test_path,
    _method_name,
    _normalize_lower_list,
    _normalize_output_format,
    _normalize_sections,
    _normalize_string_list,
    _overfetch_limit,
    _package_name,
    _starts_with_any,
    _strip_nones,
    _to_table_json,
    _trim_overfetch,
    _with_result_meta,
)
from memgraph_ingester_tool.tools._vector_index import (
    CYPHER_IDENTIFIER_RE,
    PROJECT_TOKEN_HASH_LENGTH,
    PROJECT_TOKEN_SLUG_LIMIT,
    _project_index_slug,
    _project_index_token,
    _project_vector_index_name,
    _select_vector_index_name,
    _vector_index_names,
)
from memgraph_ingester_tool.tools.code_analysis import (
    DEFAULT_OPERATION_SINKS,
    HOT_PATH_SECTIONS,
    CodeAnalysisTools,
)
from memgraph_ingester_tool.tools.code_context import CodeContextTools
from memgraph_ingester_tool.tools.memory import MemoryTools


class MemgraphTools(CodeContextTools, CodeAnalysisTools, MemoryTools):
    """Query tools for Memgraph knowledge graphs created by memgraph-ingester."""


__all__ = [
    "AUTO_QUERY_STOPWORDS",
    "CALL_GRAPH_LIMIT",
    "CAMEL_BOUNDARY_RE",
    "CONTROLLED_VALUES",
    "CYPHER_IDENTIFIER_RE",
    "DEFAULT_OPERATION_SINKS",
    "DEFAULT_RAG_ROLES",
    "DISCOVERY_LIMIT",
    "HOT_PATH_SECTIONS",
    "LEXICAL_RRF_WEIGHT",
    "LOOKUP_LIMIT",
    "MEMBER_LIMIT",
    "MEMORY_CHUNK_EXCLUDED_PROPERTIES",
    "MEMORY_SPECS",
    "OUTPUT_FORMATS",
    "PROJECT_TOKEN_HASH_LENGTH",
    "PROJECT_TOKEN_SLUG_LIMIT",
    "READ_ONLY_PREFIXES",
    "RESOURCE_SCAN_EXTENSIONS",
    "ROOT_MATCH_RE",
    "RRF_K",
    "SQL_WRITE_WITHOUT_WHERE_RE",
    "STRING_RE",
    "TARGET_TYPES",
    "TOKEN_RE",
    "UNBOUNDED_GRAPH_TRAVERSAL_RE",
    "WRITE_KEYWORDS",
    "MemgraphTools",
    "ToolClient",
    "ToolConfig",
    "ToolError",
    "_aggregate_resource_risks",
    "_bounded_depth",
    "_bounded_limit",
    "_bounded_skip",
    "_bounded_symbol_limit",
    "_bounded_text_limit",
    "_compact_owner",
    "_compact_text",
    "_contains_any",
    "_dedupe_chunk_rows",
    "_ensure_project_scoped",
    "_ensure_read_only_query",
    "_first",
    "_format_response",
    "_fragment_rank",
    "_group_limited",
    "_identifier_terms",
    "_is_test_path",
    "_lexical_query_terms",
    "_memory_label_predicate",
    "_memory_schema_entry",
    "_memory_spec",
    "_method_name",
    "_normalize_extensions",
    "_normalize_lower_list",
    "_normalize_output_format",
    "_normalize_sections",
    "_normalize_string_list",
    "_overfetch_limit",
    "_package_name",
    "_passes_chunk_filters",
    "_project_index_slug",
    "_project_index_token",
    "_project_vector_index_name",
    "_query_variants",
    "_resource_risk_rows",
    "_rrf_fuse",
    "_select_vector_index_name",
    "_source_excerpt",
    "_starts_with_any",
    "_strip_nones",
    "_strip_strings",
    "_target_match",
    "_test_fragment_parts",
    "_to_table_json",
    "_trim_overfetch",
    "_validate_target_type",
    "_vector_index_names",
    "_with_result_meta",
]
