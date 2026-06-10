"""Static resource-risk heuristics for query/config files (Cypher, SQL, etc.)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from memgraph_ingester_tool.tools._support import _compact_text, _normalize_lower_list

RESOURCE_SCAN_EXTENSIONS = (
    ".cypher",
    ".sql",
    ".graphql",
    ".gql",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".xml",
    ".properties",
)
UNBOUNDED_GRAPH_TRAVERSAL_RE = re.compile(r"\[[^\]]*\*\s*\d*\.\.[^\d\]]*\]")
ROOT_MATCH_RE = re.compile(r"\b(?:OPTIONAL\s+)?MATCH\s*\([^)]*\{[^}]+}[^)]*\)", re.IGNORECASE)
SQL_WRITE_WITHOUT_WHERE_RE = re.compile(
    r"\b(?:DELETE\s+FROM|UPDATE)\b(?:(?!\bWHERE\b).)*$",
    re.IGNORECASE,
)


def _normalize_extensions(value: Sequence[str] | str | None) -> list[str]:
    raw = _normalize_lower_list(value)
    if not raw:
        return list(RESOURCE_SCAN_EXTENSIONS)
    return [item if item.startswith(".") else f".{item}" for item in raw]


def _source_excerpt(value: str | None) -> str:
    if not value:
        return ""
    marker = "Source excerpt:\n"
    if marker not in value:
        return value
    return value.split(marker, 1)[1]


def _resource_risk_rows(path: str, language: str | None, text: str) -> list[dict[str, Any]]:
    excerpt = _source_excerpt(text)
    lines = excerpt.splitlines()
    lowered = excerpt.lower()
    rows: list[dict[str, Any]] = []

    def add(
        *,
        risk: str,
        score: int,
        pattern: str,
        line: int | None,
        evidence: str,
        why: str,
    ) -> None:
        rows.append(
            {
                "path": path,
                "language": language,
                "risk": risk,
                "score": score,
                "pattern": pattern,
                "line": line,
                "evidence": _compact_text(evidence.strip(), 180),
                "why": why,
                "occurrences": 1,
            }
        )

    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if UNBOUNDED_GRAPH_TRAVERSAL_RE.search(stripped):
            add(
                risk="high",
                score=90,
                pattern="unbounded-variable-length-traversal",
                line=index,
                evidence=stripped,
                why=(
                    "Variable-length graph traversal has no upper bound; "
                    "cost can grow with hierarchy depth."
                ),
            )
        if " like '%" in stripped.lower():
            add(
                risk="medium",
                score=45,
                pattern="leading-wildcard-like",
                line=index,
                evidence=stripped,
                why="Leading-wildcard LIKE predicates usually cannot use normal indexes.",
            )
        if SQL_WRITE_WITHOUT_WHERE_RE.search(stripped):
            add(
                risk="high",
                score=85,
                pattern="write-without-where",
                line=index,
                evidence=stripped,
                why="UPDATE/DELETE without a WHERE clause can touch every row.",
            )

    unwind_count = lowered.count("unwind ")
    traversal_count = len(UNBOUNDED_GRAPH_TRAVERSAL_RE.findall(excerpt))
    optional_match_count = lowered.count("optional match")
    merge_count = lowered.count("merge ")
    call_block_count = lowered.count("call {")
    root_matches = ROOT_MATCH_RE.findall(excerpt)
    repeated_root_matches = len(root_matches) - len(set(root_matches))

    if unwind_count and traversal_count:
        add(
            risk="high",
            score=95 + min(20, traversal_count * 3),
            pattern="per-row-unbounded-traversal",
            line=None,
            evidence=f"UNWIND x{unwind_count}, unbounded traversals x{traversal_count}",
            why="An UNWIND-driven query can repeat unbounded graph traversals once per input row.",
        )
    if unwind_count and optional_match_count >= 3:
        add(
            risk="medium",
            score=60 + min(20, optional_match_count * 2),
            pattern="per-row-many-optional-matches",
            line=None,
            evidence=f"UNWIND x{unwind_count}, OPTIONAL MATCH x{optional_match_count}",
            why="Many OPTIONAL MATCH clauses under an UNWIND can multiply per-row query work.",
        )
    if unwind_count and merge_count >= 3:
        add(
            risk="medium",
            score=55 + min(20, merge_count * 2),
            pattern="per-row-many-merges",
            line=None,
            evidence=f"UNWIND x{unwind_count}, MERGE x{merge_count}",
            why="Many MERGE operations under an UNWIND can create repeated index lookups/writes.",
        )
    if call_block_count >= 3:
        add(
            risk="medium",
            score=55 + min(25, call_block_count * 3),
            pattern="many-subquery-blocks",
            line=None,
            evidence=f"CALL {{ blocks x{call_block_count}",
            why="Many sequential subquery blocks can repeatedly rematch the same roots.",
        )
    if repeated_root_matches > 0:
        add(
            risk="medium",
            score=50 + min(30, repeated_root_matches * 5),
            pattern="repeated-root-rematch",
            line=None,
            evidence=f"Repeated root MATCH patterns x{repeated_root_matches}",
            why="Repeatedly matching the same keyed root in one resource is often avoidable.",
        )
    if "foreach" in lowered and any(token in lowered for token in (" set ", " remove ", " merge ")):
        add(
            risk="medium",
            score=50,
            pattern="write-inside-foreach",
            line=None,
            evidence="FOREACH with write clauses",
            why=(
                "FOREACH with write clauses. Verify this is not a per-row write loop; "
                "single-item conditional FOREACH (CASE THEN [1] ELSE []) is idiomatic and safe."
            ),
        )

    return rows


def _aggregate_resource_risks(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row.get("path") or "", row.get("pattern") or "")
        current = grouped.get(key)
        if current is None:
            grouped[key] = dict(row)
            continue
        current["occurrences"] = (current.get("occurrences") or 1) + 1
        current["score"] = max(current.get("score") or 0, row.get("score") or 0) + min(
            15,
            current["occurrences"],
        )
        if current.get("line") is None or (
            row.get("line") is not None and row["line"] < current["line"]
        ):
            current["line"] = row.get("line")
            current["evidence"] = row.get("evidence")
    return list(grouped.values())
