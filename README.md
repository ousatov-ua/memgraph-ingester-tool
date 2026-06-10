# memgraph-ingester-tool

[![PyPI release](https://img.shields.io/pypi/v/memgraph-ingester-tool)](https://pypi.org/project/memgraph-ingester-tool/)
[![Python versions](https://img.shields.io/pypi/pyversions/memgraph-ingester-tool)](https://pypi.org/project/memgraph-ingester-tool/)
[![License](https://img.shields.io/pypi/l/memgraph-ingester-tool)](https://github.com/ousatov-ua/memgraph-ingester-tool/blob/main/LICENSE)

Standalone query tools for Memgraph knowledge graphs produced by
[`memgraph-ingester`](https://github.com/ousatov-ua/memgraph-ingester).

This package is the **single source of truth** for all graph query and
formatting logic. It is consumed two ways:

- as a **library** by [`memgraph-ingester-mcp`](https://github.com/ousatov-ua/memgraph-ingester-mcp),
  which exposes every method as an MCP tool;
- as a **CLI** (`mgtools`) for users who work with `mgconsole` or scripts and
  have no MCP client.

Any change to query logic here automatically reaches both audiences.

## Installation

```bash
pip install memgraph-ingester-tool
# or
uv tool install memgraph-ingester-tool
```

## Configuration

Settings come from environment variables. `MEMGRAPH_TOOLS_*` take priority;
`MEMGRAPH_INGESTER_MCP_*` are accepted as a fallback so existing MCP
configurations keep working.

| Variable | Default | Description |
| --- | --- | --- |
| `MEMGRAPH_TOOLS_BOLT_URI` | `bolt://127.0.0.1:7687` | Memgraph Bolt endpoint |
| `MEMGRAPH_TOOLS_USERNAME` | _none_ | Bolt username |
| `MEMGRAPH_TOOLS_PASSWORD` | _none_ | Bolt password |
| `MEMGRAPH_TOOLS_DATABASE` | _none_ | Database name |
| `MEMGRAPH_TOOLS_PROJECT` | _none_ | Default project (`:Project` anchor name) |
| `MEMGRAPH_TOOLS_QUERY_TIMEOUT_SECONDS` | `30.0` | Per-query timeout |
| `MEMGRAPH_TOOLS_READ_ONLY` | `false` | Disable write operations |
| `MEMGRAPH_TOOLS_CODE_EMBEDDING_INDEX` | `code_chunk_embedding_v2` | Code vector index base name |
| `MEMGRAPH_TOOLS_MEMORY_EMBEDDING_INDEX` | `memory_chunk_embedding_v2` | Memory vector index base name |
| `MEMGRAPH_TOOLS_EMBEDDING_MODEL` | `default` | Embedding model name |
| `MEMGRAPH_TOOLS_EMBEDDING_DIMENSIONS` | `384` | Embedding dimensions |

## Endpoints

Every endpoint below is exposed twice from the same implementation: as a public
method on `MemgraphTools` and as an `mgtools` subcommand of the same name. The
[`memgraph-ingester-mcp`](https://github.com/ousatov-ua/memgraph-ingester-mcp)
server registers the identical set as MCP tools.

### Code graph endpoints

| Endpoint | Description |
| --- | --- |
| `server_status` | Graph inventory, memory counts, and vector index status for a project. |
| `code_orientation` | Compact package/type/call overview; pass `sections` to keep it focused. |
| `code_search` | Hybrid CodeChunk search — vector + lexical signals fused by reciprocal rank; defaults to 5 non-test, deduped, primary/file-role hits with compact filters (`kinds`, `path_prefixes`, `path_contains`, `owner_fragment`, `min_score`). |
| `code_text_search` | Ranked lexical search over indexed chunk text/path/source ids for concrete-term discovery; returns `termMatches`. |
| `code_discovery_context` | Semantic discovery plus bounded exact/caller/callee/file context in one compact response. |
| `code_flow_context` | Workflow discovery with semantic/lexical anchors, likely file outlines, related paths, and bounded nearby call edges; pass `detail="full"` for wider expansion. |
| `code_file_context` | Deterministic file outlines with language, definition/chunk counts, RAG role counts, and top symbols. |
| `code_lookup_type` | Exact class/interface/annotation lookup by name or FQN; member expansion and test code are opt-in. |
| `code_lookup_methods` | Exact method lookup by signature fragment with source ranges; defaults to 10 compact owner/name/path rows. |
| `code_lookup_field` | Exact field/constant lookup by FQN or name fragment; compact owner/name/FQN/path rows. |
| `code_lookup_file` | Indexed file/resource lookup by path fragment with definition and RAG chunk counts. |
| `code_callers` | Methods that call matching callee signatures; compact, paginated, range-first rows. |
| `code_callees` | Callees invoked by matching caller signatures; compact, paginated, range-first rows. |
| `code_method_context` | Bundled exact method lookup plus caller and callee context for tracing one target. |
| `code_impact` | Refactor blast-radius for matching method signatures: target methods plus depth-1/depth-2 callers, test flags, and file/package boundary flags; `view="files"` returns a risk-ranked file list. |
| `code_hot_paths` | Hot-path candidates from type size, method size, fan-in, and fan-out; `include_evidence=true` adds source locations. |
| `code_operation_hot_paths` | Methods with many calls into operation-like sinks (run/query/write/read/save/delete…); accepts owner/path filters for subsystem audits. |
| `code_resource_risk_scan` | Heuristic scan of query/config/resource files for risky patterns such as unbounded graph traversals, repeated subqueries, and per-row writes. |
| `code_quality_stats` | Graph-wide code quality and quantity metrics; defaults to non-test code. |
| `code_hierarchy` | Class ancestry, children, interfaces, and interface implementors for one FQN. |
| `code_test_context` | Failing-test/CI triage from a test name or class fragment to tests, test files, and production callees. |
| `raw_read_cypher` | Read-only, project-scoped Cypher escape hatch for edge cases. |

### Memory endpoints

| Endpoint | Description |
| --- | --- |
| `memory_orientation` | Rules plus open findings, tasks, questions, and risks; `compact=true` omits body fields. |
| `memory_schema` | Allowed memory types, upsert fields, controlled values, and CodeRef targets. |
| `memory_search` | MemoryChunk vector search with index-only hit metadata. |
| `memory_get` | Canonical memory node plus resolved CodeRefs. |
| `memory_upsert` | Create/update `Decision`, `ADR`, `Rule`, `Context`, `Finding`, `Task`, `Risk`, `Question`, or `Idea`. |
| `memory_update_status` | Lifecycle status update with controlled-value validation. |
| `delete_memory` | Delete one memory node plus its derived chunk and orphan CodeRefs. |
| `memory_link_code_ref` | Link a memory node to a resolved `Code`/`Package`/`File`/`Class`/`Interface`/`Annotation`/`Method`/`Field` target. |
| `memory_refresh_chunk` | Rebuild one derived MemoryChunk (optionally re-embedding it). |
| `memory_refresh_embeddings` | Refresh embeddings for selected MemoryChunk ids and stamp metadata. |

Write operations (`memory_upsert`, `memory_update_status`, `delete_memory`,
`memory_link_code_ref`, `memory_refresh_chunk`, `memory_refresh_embeddings`)
are rejected when `MEMGRAPH_TOOLS_READ_ONLY=true`.

## CLI usage

Every endpoint above is available as an `mgtools` subcommand:

```bash
# graph inventory, memory counts, vector indexes
mgtools server_status --project my-project

# hybrid vector + lexical code search
mgtools code_search "authentication filter" --project my-project --limit 5

# exact lookups
mgtools code_lookup_methods "GraphWriter.upsertFile" --project my-project
mgtools code_lookup_type --type-name GraphWriter --project my-project

# call graph and refactor impact
mgtools code_callers "GraphWriter.upsertFile" --project my-project
mgtools code_impact "upsertFile" --view files --project my-project

# memory tools
mgtools memory_orientation --project my-project --compact
mgtools memory_search "ingestion pipeline decisions" --project my-project

# read-only Cypher escape hatch (project filter required)
mgtools raw_read_cypher \
  "MATCH (f:File {project: \$project}) RETURN f.path LIMIT 10" \
  --project my-project
```

Run `mgtools --help` for the full command list and `mgtools <command> --help`
for per-command options. `python -m memgraph_ingester_tool` works as well.

## Library usage

```python
from memgraph_ingester_tool import MemgraphTools, ToolConfig

tools = MemgraphTools(ToolConfig(default_project="my-project"))
status = tools.server_status()
hits = tools.code_search("authentication filter", limit=5)
```

`MemgraphTools` also accepts a pre-built client (anything implementing
`run(query, parameters, *, write=False)`), which is how the MCP server reuses
its own connection:

```python
tools = MemgraphTools(config, client=my_client)
```

## Output formats

Row-heavy commands default to `table_json` — a compact `{cols: [...], rows: [...]}`
encoding. Pass `--format json` for plain objects. Absent keys mean null or
empty, never an error.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

## License

MIT
