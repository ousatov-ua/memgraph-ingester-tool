"""Safety guards for raw_read_cypher: read-only and project-scoping validation."""

from __future__ import annotations

import re

from memgraph_ingester_tool.db import ToolError
from memgraph_ingester_tool.schema import READ_ONLY_PREFIXES, WRITE_KEYWORDS

TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
STRING_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


def _strip_strings(query: str) -> str:
    return STRING_RE.sub("''", query)


def _ensure_read_only_query(query: str) -> None:
    stripped = query.strip()
    if not stripped:
        raise ToolError("Cypher query cannot be empty.")

    lowered = stripped.lower()
    if not lowered.startswith(READ_ONLY_PREFIXES):
        raise ToolError("Only read-oriented Cypher is allowed.")

    tokens = {token.lower() for token in TOKEN_RE.findall(_strip_strings(lowered))}
    used_write_keywords = sorted(tokens & WRITE_KEYWORDS)
    if used_write_keywords:
        joined = ", ".join(used_write_keywords)
        raise ToolError(f"Raw read query contains write keyword(s): {joined}.")

    write_procedures = ("embeddings.node_sentence", "node2vec.set_embeddings")
    if any(proc in lowered for proc in write_procedures):
        raise ToolError("Writeable procedures are not allowed through raw_read_cypher.")


def _ensure_project_scoped(query: str) -> None:
    lowered = query.lower()
    metadata_query = lowered.startswith("show vector index info") or "call mg.procedures" in lowered
    if metadata_query:
        return
    if "$project" not in query and "project:" not in lowered and "project =" not in lowered:
        raise ToolError(
            "Raw read queries must include a project filter such as project: $project."
        )
