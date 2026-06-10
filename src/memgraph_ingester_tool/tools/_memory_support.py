"""Memory-node helpers: specs, controlled vocabularies, and code-ref target matching."""

from __future__ import annotations

from typing import Any

from memgraph_ingester_tool.db import ToolError
from memgraph_ingester_tool.schema import MEMORY_SPECS, TARGET_TYPES

CONTROLLED_VALUES: dict[tuple[str, str], frozenset[str]] = {
    ("Rule", "severity"): frozenset({"hard", "soft", "recommendation"}),
    ("Finding", "type"): frozenset({"bug", "perf", "constraint", "security"}),
    ("Finding", "status"): frozenset({"open", "resolved", "obsolete"}),
    ("Task", "priority"): frozenset({"0", "1", "2", "3", "4"}),
    ("Task", "status"): frozenset({"todo", "doing", "done", "blocked", "cancelled"}),
    ("Risk", "severity"): frozenset({"low", "medium", "high", "critical"}),
    ("Risk", "status"): frozenset({"open", "mitigated", "accepted", "obsolete"}),
    ("Question", "status"): frozenset({"open", "answered", "obsolete"}),
    ("Decision", "status"): frozenset({"proposed", "accepted", "rejected", "superseded"}),
    ("ADR", "status"): frozenset({"draft", "proposed", "accepted", "rejected", "superseded"}),
    ("Idea", "status"): frozenset({"proposed", "accepted", "rejected", "obsolete"}),
}

# Mirrors MEMORY_CHUNK_METADATA_PROPERTIES in the ingester's EmbeddingSettings so MCP-side
# MemoryChunk refreshes produce embeddings consistent with ingester-side refreshes.
MEMORY_CHUNK_EXCLUDED_PROPERTIES = (
    "id",
    "project",
    "sourceLabel",
    "sourceId",
    "textHash",
    "embedding",
    "embeddingModel",
    "embeddingDimensions",
    "createdAt",
    "updatedAt",
)


def _memory_spec(memory_type: str):
    spec = MEMORY_SPECS.get(memory_type)
    if spec is None:
        allowed = ", ".join(sorted(MEMORY_SPECS))
        raise ToolError(f"Unsupported memory_type {memory_type!r}. Allowed: {allowed}.")
    return spec


def _memory_schema_entry(memory_type: str) -> dict[str, Any]:
    spec = _memory_spec(memory_type)
    return {
        "label": spec.label,
        "relation": spec.relation,
        "fields": sorted(spec.fields),
        "controlledValues": {
            field: sorted(values)
            for (type_name, field), values in sorted(CONTROLLED_VALUES.items())
            if type_name == memory_type
        },
    }


def _memory_label_predicate(variable: str = "memory") -> str:
    return " OR ".join(f"{variable}:{spec.label}" for spec in MEMORY_SPECS.values())


def _validate_target_type(target_type: str) -> None:
    if target_type not in TARGET_TYPES:
        allowed = ", ".join(sorted(TARGET_TYPES))
        raise ToolError(f"Unsupported target_type {target_type!r}. Allowed: {allowed}.")


def _target_match(target_type: str) -> tuple[str, str]:
    _validate_target_type(target_type)
    match target_type:
        case "Code":
            return "Code", "target.language = $target_key"
        case "Package":
            return (
                "Package",
                "(target.name = $target_key OR target.language + ':' + target.name = $target_key)",
            )
        case "File":
            return "File", "target.path = $target_key"
        case "Method":
            return "Method", "target.signature = $target_key"
        case "Field":
            return "Field", "target.fqn = $target_key"
        case "Class" | "Interface" | "Annotation":
            return target_type, "target.fqn = $target_key"
    raise ToolError(f"Unsupported target_type {target_type!r}.")
