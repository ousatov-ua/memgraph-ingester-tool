"""Search-side helpers: lexical term extraction, chunk filtering, and RRF fusion."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from memgraph_ingester_tool.tools._support import _contains_any, _starts_with_any

CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+")
DEFAULT_RAG_ROLES = ("primary", "file")
RRF_K = 60
# Down-weight the lexical leg so file-role chunks with large Words vocabularies don't override
# vector hits for concept queries. 0.4 gives lexical a meaningful boost for exact-term matches
# while keeping vector-only hits competitive.
LEXICAL_RRF_WEIGHT = 0.4
AUTO_QUERY_STOPWORDS = frozenset(
    {
        "all",
        "any",
        "are",
        "can",
        "class",
        "does",
        "file",
        "files",
        "from",
        "get",
        "has",
        "how",
        "not",
        "last",
        "line",
        "method",
        "node",
        "nodes",
        "path",
        "project",
        "set",
        "source",
        "state",
        "test",
        "tests",
        "that",
        "the",
        "this",
        "time",
        "type",
        "value",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
)


def _identifier_terms(value: str | None) -> list[str]:
    if not value:
        return []
    terms = [term.lower() for term in CAMEL_BOUNDARY_RE.split(value) if len(term) >= 3]
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


def _lexical_query_terms(value: str | None, *, min_length: int = 3) -> list[str]:
    return [
        term
        for term in _identifier_terms(value)
        if len(term) >= min_length and term not in AUTO_QUERY_STOPWORDS
    ]


def _query_variants(query: str) -> list[str]:
    """Return the raw query plus a keyword variant when it adds embedding signal.

    The keyword variant lowercases and camel-splits the query so identifier-style
    queries also match the split-word vocabulary embedded in chunk texts.
    """
    variants = [query]
    keyword_variant = " ".join(_lexical_query_terms(query))
    if keyword_variant and keyword_variant != query.strip().lower():
        variants.append(keyword_variant)
    return variants


def _passes_chunk_filters(
    row: Mapping[str, Any],
    *,
    kind_filter: frozenset[str] | set[str],
    path_prefix_filter: Sequence[str],
    path_contains_filter: str,
    owner_filter: str,
    min_score: float,
) -> bool:
    """Apply code_search post-filters; min_score only gates rows carrying a vector score."""
    if kind_filter and row.get("kind") not in kind_filter:
        return False
    if not _starts_with_any(row.get("path"), path_prefix_filter):
        return False
    if path_contains_filter and path_contains_filter not in (row.get("path") or ""):
        return False
    if owner_filter and not _contains_any(row.get("owner"), [owner_filter]):
        return False
    # Lexical-only rows carry no vector score; drop them when min_score is active.
    return not (min_score > 0 and ("score" not in row or float(row.get("score") or 0) < min_score))


def _dedupe_chunk_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the first (best-ranked) row per (kind, sourceId)."""
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.get("kind") or "", row.get("sourceId") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(row))
    return deduped


def _rrf_fuse(
    vector_rows: Sequence[Mapping[str, Any]],
    lexical_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge two ranked candidate lists with reciprocal rank fusion.

    Rank-based fusion is immune to the uncalibrated absolute similarity scores; vector
    rows win ties via their score and contribute the row payload, lexical rows attach
    termMatches when they agree on the same chunk.
    """
    fused: dict[tuple[str, str], dict[str, Any]] = {}
    scores: dict[tuple[str, str], float] = {}
    for rank, row in enumerate(vector_rows):
        key = (row.get("kind") or "", row.get("sourceId") or "")
        fused.setdefault(key, dict(row))
        scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
    for rank, row in enumerate(lexical_rows):
        key = (row.get("kind") or "", row.get("sourceId") or "")
        if key in fused:
            if row.get("termMatches") is not None:
                fused[key]["termMatches"] = row.get("termMatches")
        else:
            fused[key] = dict(row)
        scores[key] = scores.get(key, 0.0) + LEXICAL_RRF_WEIGHT / (RRF_K + rank + 1)
    ordered = sorted(
        fused.items(),
        key=lambda item: (
            -scores[item[0]],
            -float(item[1].get("score") or 0.0),
            item[1].get("path") or "",
        ),
    )
    return [row for _key, row in ordered]


def _test_fragment_parts(value: str | None) -> tuple[str, str, list[str], int]:
    fragment = (value or "").strip()
    if "." not in fragment:
        terms = _identifier_terms(fragment)
        return "", fragment, terms, 1 if len(terms) <= 2 else 2

    owner_fragment, method_fragment = fragment.rsplit(".", 1)
    terms = _identifier_terms(method_fragment) or _identifier_terms(fragment)
    method_terms = [term for term in terms if len(term) >= 5]
    if method_terms:
        terms = method_terms
    min_matches = min(3, max(1, len(terms) - 1))
    return owner_fragment, method_fragment, terms, min_matches
