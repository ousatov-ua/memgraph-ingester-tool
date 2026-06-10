"""Project-scoped vector index naming and selection."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

from memgraph_ingester_tool.db import ToolError

CYPHER_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")
PROJECT_TOKEN_SLUG_LIMIT = 48
PROJECT_TOKEN_HASH_LENGTH = 12


def _project_vector_index_name(base_index_name: str, project: str) -> str:
    if not CYPHER_IDENTIFIER_RE.fullmatch(base_index_name):
        raise ToolError("Embedding vector index base name must be a Cypher identifier.")
    normalized = project.strip()
    if not normalized:
        raise ToolError("Project is required for project-scoped vector index lookup.")
    return f"{base_index_name}_{_project_index_token(normalized)}"


def _project_index_token(project: str) -> str:
    slug = _project_index_slug(project)
    digest = sha256(project.encode()).hexdigest()[:PROJECT_TOKEN_HASH_LENGTH]
    return f"p_{slug}_{digest}"


def _project_index_slug(project: str) -> str:
    slug = []
    pending_underscore = False
    for ch in project:
        if ch.isascii() and ch.isalnum():
            if pending_underscore and slug:
                slug.append("_")
            slug.append(ch.lower())
            pending_underscore = False
        elif slug:
            pending_underscore = True
        if len(slug) >= PROJECT_TOKEN_SLUG_LIMIT:
            break
    return "".join(slug) or "project"


def _select_vector_index_name(
    base_index_name: str,
    project: str,
    available_index_names: set[str],
) -> str:
    project_index_name = _project_vector_index_name(base_index_name, project)
    if project_index_name in available_index_names:
        return project_index_name
    if base_index_name in available_index_names:
        return base_index_name
    return project_index_name


def _vector_index_names(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(row.get("index_name")) for row in rows if row.get("index_name") is not None}
