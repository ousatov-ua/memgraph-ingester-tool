"""Generic plumbing shared by all tool mixins: bounds, normalization, response shaping."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from memgraph_ingester_tool.db import ToolError

OUTPUT_FORMATS = frozenset({"json", "table_json"})
DISCOVERY_LIMIT = 5
LOOKUP_LIMIT = 10
CALL_GRAPH_LIMIT = 10
MEMBER_LIMIT = 25


def _bounded_limit(limit: int, *, default: int, maximum: int) -> int:
    if limit <= 0:
        return default
    return min(limit, maximum)


def _bounded_skip(skip: int) -> int:
    return max(skip, 0)


def _compact_text(value: str | None, limit: int = 600) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}..."


def _bounded_text_limit(limit: int) -> int:
    if limit <= 0:
        return 0
    return min(limit, 2_000)


def _bounded_depth(depth: int) -> int:
    if depth <= 1:
        return 1
    return min(depth, 2)


def _bounded_symbol_limit(limit: int) -> int:
    return _bounded_limit(limit, default=8, maximum=50)


def _first(value: Any) -> Any:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return value[0] if value else None
    return value


def _method_name(signature: str | None) -> str | None:
    if not signature:
        return None
    return signature.rsplit(".", 1)[-1].split("(", 1)[0]


def _compact_owner(owner: str | None, name: str | None) -> str | None:
    if not owner or not name:
        return owner
    if owner == name or owner.endswith(f".{name}") or owner.endswith(f"#{name}"):
        return None
    return owner


def _package_name(owner_fqn: str | None) -> str | None:
    if not owner_fqn or "." not in owner_fqn:
        return None
    return owner_fqn.rsplit(".", 1)[0]


def _is_test_path(path: str | None) -> bool:
    return bool(
        path
        and (
            path.startswith(("src/test/", "test/", "tests/"))
            or "/test/" in path
            or "/tests/" in path
        )
    )


def _normalize_string_list(value: Sequence[str] | str | None) -> list[str]:
    if value is None:
        return []
    raw = value.split(",") if isinstance(value, str) else list(value)
    return [item.strip() for item in raw if item and item.strip()]


def _normalize_lower_list(value: Sequence[str] | str | None) -> list[str]:
    return [item.lower() for item in _normalize_string_list(value)]


def _contains_any(value: str | None, needles: Sequence[str]) -> bool:
    if not needles:
        return True
    haystack = (value or "").lower()
    return any(needle.lower() in haystack for needle in needles)


def _starts_with_any(value: str | None, prefixes: Sequence[str]) -> bool:
    if not prefixes:
        return True
    haystack = value or ""
    return any(haystack.startswith(prefix) for prefix in prefixes)


def _normalize_output_format(output_format: str | None) -> str:
    if output_format is None:
        return "json"
    normalized = output_format.strip()
    if normalized not in OUTPUT_FORMATS:
        allowed = ", ".join(sorted(OUTPUT_FORMATS))
        raise ToolError(f"Unsupported format {output_format!r}. Allowed: {allowed}.")
    return normalized


def _strip_nones(obj: Any) -> Any:
    """Recursively remove None-valued keys from dicts. Absent keys signal null/empty to callers."""
    if isinstance(obj, Mapping):
        return {k: _strip_nones(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nones(item) for item in obj]
    return obj


def _to_table_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _to_table_json(item) for key, item in value.items()}
    if isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value):
        columns: list[str] = []
        for row in value:
            for key in row:
                column = str(key)
                if column not in columns:
                    columns.append(column)
        # Drop columns that are None in every row — callers should treat absent as null.
        live_columns = [col for col in columns if any(row.get(col) is not None for row in value)]
        return {
            "cols": live_columns,
            "rows": [[_to_table_json(row.get(col)) for col in live_columns] for row in value],
        }
    return value


def _format_response(
    response: dict[str, Any],
    output_format: str | None = "json",
) -> dict[str, Any]:
    normalized = _normalize_output_format(output_format)
    if normalized == "json":
        return _strip_nones(response)

    formatted = _to_table_json(response)
    if not isinstance(formatted, dict):  # pragma: no cover - response is always a dict today.
        raise ToolError("Formatted response must be an object.")

    return formatted


def _with_result_meta(
    response: dict[str, Any],
    rows: Sequence[Any],
    *,
    skip: int = 0,
    limit: int | None = None,
    total_count: int | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    returned_count = len(rows)
    total = returned_count if total_count is None else total_count
    next_skip = skip + returned_count
    has_more = next_skip < total
    meta: dict[str, Any] = {"hasMore": True} if has_more else {}
    if has_more:
        meta["nextSkip"] = next_skip
    if total_count is not None and total > returned_count:
        meta["totalCount"] = total
    if extra:
        meta.update(extra)
    response["meta"] = meta
    return response


def _overfetch_limit(limit_value: int, include_count: bool) -> int:
    return limit_value if include_count else limit_value + 1


def _trim_overfetch(
    rows: list[dict[str, Any]],
    *,
    skip: int,
    limit: int,
    include_count: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if include_count or len(rows) <= limit:
        return rows, None
    trimmed = rows[:limit]
    return trimmed, {"hasMore": True, "nextSkip": skip + len(trimmed)}


def _normalize_sections(
    sections: Sequence[str] | str | None,
    *,
    allowed: frozenset[str],
    default: frozenset[str],
) -> frozenset[str]:
    if sections is None:
        return default
    raw = sections.split(",") if isinstance(sections, str) else list(sections)
    requested = frozenset(section.strip() for section in raw if section and section.strip())
    unknown = sorted(requested - allowed)
    if unknown:
        raise ToolError(
            f"Unknown section(s): {', '.join(unknown)}. Allowed: {', '.join(sorted(allowed))}."
        )
    return requested or default


def _group_limited(
    rows: Sequence[Mapping[str, Any]],
    *,
    key: str = "path",
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group_key = row.get(key)
        if not isinstance(group_key, str) or not group_key:
            continue
        bucket = grouped.setdefault(group_key, [])
        if len(bucket) < limit:
            item = dict(row)
            item.pop(key, None)
            bucket.append(item)
    return grouped


def _fragment_rank(path: str | None, fragments: Sequence[str]) -> tuple[int, str]:
    if not path:
        return (len(fragments), "")
    for index, fragment in enumerate(fragments):
        if fragment in path:
            return (index, path)
    return (len(fragments), path)
