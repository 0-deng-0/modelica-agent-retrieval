import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .doc_ids import normalize_doc_id
from .index_builder import OfflineSearchIndex, build_index_from_documents, load_index, save_index
from .retriever import lookup_by_path, lookup_by_section_path, search_components
from .text_utils import kind_matches


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT_ROOT / "search" / "index"
REGISTRY_PATH = INDEX_DIR / "index.json"
_INDEX_CACHE: Dict[str, OfflineSearchIndex] = {}
SCHEMA_VERSION = "search-api-v1.2"
DEFAULT_MIN_CONFIDENCE = 0.15


def run_search_api(action: str, **kwargs: Any) -> dict:
    """Build and use registered Modelica indexes by doc_id.

    Actions:
      - build: input_json_path, format, doc_id, optional description
      - search: query, optional doc_id/query_variants/final_k/debug
      - get: paths and/or section_paths, optional doc_id/fields
      - list-children: optional doc_id/parent/kind
      - list-docs: list registered indexes
      - health: report registry status
    """
    started = time.perf_counter()
    strict = _as_bool(kwargs.pop("strict", False), "strict")
    warnings_out: List[str] = []
    action_name = str(action or "").strip().lower()
    try:
        if action_name == "build":
            data = _build(
                input_json_path=_required_str(kwargs, "input_json_path"),
                doc_format=_required_str(kwargs, "format").lower(),
                raw_doc_id=_required_str(kwargs, "doc_id"),
                description=str(kwargs.get("description") or kwargs.get("desc") or ""),
                warnings_out=warnings_out,
            )
        elif action_name == "search":
            data = _search(
                query=_required_str(kwargs, "query"),
                doc_ids=_optional_doc_ids(kwargs.get("doc_id")),
                query_variants=_optional_str_list(
                    kwargs.get("query_variants"), "query_variants"
                ),
                topk_per_variant=_positive_int(kwargs.get("topk_per_variant"), 20),
                final_k=_positive_int(kwargs.get("final_k"), 10),
                min_confidence=_bounded_float(
                    kwargs.get("min_confidence"),
                    default=DEFAULT_MIN_CONFIDENCE,
                    minimum=0.0,
                    maximum=1.0,
                ),
                debug=_as_bool(kwargs.get("debug", False), "debug"),
            )
        elif action_name == "get":
            data = _get(
                paths=_optional_str_list(kwargs.get("paths"), "paths"),
                section_paths=_optional_str_list(kwargs.get("section_paths"), "section_paths"),
                doc=kwargs.get("doc_id"),
                fields=_optional_str_list(kwargs.get("fields"), "fields"),
            )
        elif action_name == "list-children":
            data = _list_children(
                doc=kwargs.get("doc_id"),
                parent=kwargs.get("parent"),
                kind=kwargs.get("kind"),
            )
        elif action_name == "list-docs":
            data = _list_docs()
        elif action_name == "health":
            docs = _read_registry()
            data = {"registered_doc_count": len(docs)}
        else:
            raise ValueError(f"Unsupported action: {action!r}")
        return _ok_response(action_name, data, started, warnings_out)
    except Exception as exc:
        if strict:
            raise
        return _error_response(action_name, exc, started, warnings_out)


def _build(
    input_json_path: str,
    doc_format: str,
    raw_doc_id: str,
    description: str,
    warnings_out: List[str],
) -> dict:
    if doc_format not in ("msl", "spec"):
        raise ValueError("format must be 'msl' or 'spec'.")

    doc_id = normalize_doc_id(raw_doc_id)
    source_path = _resolve_path(input_json_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Source JSON not found: {source_path}")

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    registry = _read_registry()
    if doc_id in registry:
        warnings_out.append(
            f"doc_id {doc_id!r} already exists; its index and registry entry were "
            "overwritten. Other .pkl files were not deleted."
        )

    index_path = INDEX_DIR / f"{doc_id}.pkl"
    index = build_index_from_documents(
        [{"doc_id": doc_id, "format": doc_format, "path": str(source_path)}]
    )
    save_index(index, str(index_path))
    _INDEX_CACHE.pop(_cache_key(str(index_path)), None)

    registry[doc_id] = {
        "format": doc_format,
        "source_basename": source_path.name,
        "source_json": _display_path(source_path),
        "index_file": _display_path(index_path),
        "description": description,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_registry(registry)
    return {
        "status": "ok",
        "action": "build",
        "doc_id": doc_id,
        "format": doc_format,
        "source_json": _display_path(source_path),
        "index_file": _display_path(index_path),
        "doc_count": len(index.records),
        "built_at_utc": index.built_at_utc,
    }


def _search(
    query: str,
    doc_ids: Optional[List[str]],
    query_variants: Optional[List[str]],
    topk_per_variant: int,
    final_k: int,
    min_confidence: float,
    debug: bool,
) -> dict:
    registry = _read_registry()
    selected_doc_ids = _resolve_doc_ids(doc_ids, registry)
    if not selected_doc_ids:
        raise ValueError("index.json is empty. Build at least one document first.")

    candidates = []
    elapsed_ms = 0
    for doc_id in selected_doc_ids:
        entry = _registered_entry(registry, doc_id)
        index = _get_index(entry["index_file"])
        result = search_components(
            index=index,
            query=query,
            query_variants=query_variants,
            docs=[doc_id],
            topk_per_variant=topk_per_variant,
            final_k=final_k,
        )
        candidates.extend(result["candidates"])
        elapsed_ms += result["meta"]["took_ms"]

    candidates.sort(key=_candidate_sort_key)
    candidates = _deduplicate_candidates(candidates)
    if min_confidence > 0.0:
        candidates = [
            row for row in candidates if float(row.get("confidence", 0.0)) >= min_confidence
        ]
    candidates = [_candidate_payload(row, debug) for row in candidates[:final_k]]
    return {
        "query": query,
        "docs_scope": selected_doc_ids,
        "candidates": candidates,
        "meta": {
            "returned_count": len(candidates),
            "min_confidence": min_confidence,
            "debug": debug,
            "took_ms": elapsed_ms,
        },
    }


def _get(
    paths: Optional[List[str]],
    section_paths: Optional[List[str]],
    doc: Any,
    fields: Optional[List[str]],
) -> dict:
    requested: List[Tuple[str, str, str]] = []
    requested.extend(("path", value, "msl") for value in paths or [])
    requested.extend(("section_path", value, "spec") for value in section_paths or [])
    if not requested:
        raise ValueError("get requires at least one path or section_path.")

    registry = _read_registry()
    selected_doc = None
    if doc is not None and str(doc).strip():
        selected_docs = _resolve_doc_ids([str(doc)], registry)
        if len(selected_docs) != 1:
            raise ValueError(f"Expected one document, got {len(selected_docs)} for doc_id={doc!r}.")
        selected_doc = selected_docs[0]

    items = []
    for key_type, key, required_format in requested:
        matching_doc_ids = [selected_doc] if selected_doc else _docs_by_format(registry, required_format)
        hits: List[Tuple[str, dict]] = []
        for doc_id in matching_doc_ids:
            entry = _registered_entry(registry, doc_id)
            if entry.get("format") != required_format:
                if selected_doc:
                    raise ValueError(
                        f"Document {selected_doc!r} has format {entry.get('format')!r}; "
                        f"it cannot be used with {key_type}."
                    )
                continue
            index = _get_index(entry["index_file"])
            full = (
                lookup_by_path(index, key)
                if key_type == "path"
                else lookup_by_section_path(index, key)
            )
            if full is not None:
                hits.append((doc_id, full))
        if hits:
            doc_id, full = hits[0]
            payload, missing = _record_payload(full, fields)
            found = {"status": "ok", "doc_id": doc_id, key_type: key}
            found.update({name: value for name, value in payload.items() if name not in found})
            if missing:
                found["missing_fields"] = missing
            other_doc_ids = [other_doc_id for other_doc_id, _ in hits[1:]]
            if other_doc_ids:
                found["other_doc_ids"] = other_doc_ids
        else:
            found = {
                "status": "not_found",
                key_type: key,
                "doc_id": selected_doc,
                "searched_doc_ids": matching_doc_ids,
            }
        items.append(found)

    return {
        "requested_doc_id": selected_doc,
        "requested_count": len(items),
        "found_count": sum(item["status"] == "ok" for item in items),
        "items": items,
    }


def _list_docs() -> dict:
    registry = _read_registry()
    docs = [
        {
            "doc_id": doc_id,
            "format": entry.get("format"),
            "description": entry.get("description", ""),
            "updated_at_utc": entry.get("updated_at_utc"),
        }
        for doc_id, entry in sorted(registry.items())
    ]
    return {"count": len(docs), "docs": docs}


def _list_children(doc: Any, parent: Any, kind: Any) -> dict:
    registry = _read_registry()
    if not registry:
        raise ValueError("index.json is empty. Build at least one document first.")

    if doc is not None and str(doc).strip():
        selected_docs = _resolve_doc_ids([str(doc)], registry)
        if len(selected_docs) != 1:
            raise ValueError(f"Expected one document, got {len(selected_docs)} for doc_id={doc!r}.")
        doc_id = selected_docs[0]
    else:
        doc_id = _latest_doc_for_format(registry, "msl")

    entry = _registered_entry(registry, doc_id)
    if entry.get("format") != "msl":
        raise ValueError(
            f"Document {doc_id!r} has format {entry.get('format')!r}; list-children works on msl only."
        )

    parent_path = str(parent).strip() if parent is not None and str(parent).strip() else "Modelica"
    kind_filter = str(kind).strip().lower() if kind is not None and str(kind).strip() else None

    index = _get_index(entry["index_file"])
    raw_children = _package_children(index, parent_path)

    children = []
    for child in raw_children:
        child_path = str(child.get("path") or "").strip()
        if not child_path:
            continue
        child_record = index.component_by_path.get(child_path)
        child_kind = child_record["summary"].get("kind") if child_record else None
        if kind_filter and not kind_matches(child_kind, kind_filter):
            continue
        children.append(
            {
                "path": child_path,
                "name": child.get("name"),
                "kind": child_kind,
                "description": child.get("description"),
            }
        )

    return {
        "doc_id": doc_id,
        "parent": parent_path,
        "kind": kind_filter,
        "count": len(children),
        "children": children,
    }


def _package_children(index: OfflineSearchIndex, parent_path: str) -> List[dict]:
    record = lookup_by_path(index, parent_path)
    if record is not None:
        children = record.get("subClasses")
        if children is None:
            children = record.get("package_content")
        return [child for child in children or [] if isinstance(child, dict)]

    # The parent may not itself be indexed (e.g. trimmed libraries): fall back to
    # a prefix scan so browsing still works.
    prefix = parent_path + "."
    children = []
    for path, child_record in index.component_by_path.items():
        if not path.startswith(prefix) or "." in path[len(prefix):]:
            continue
        summary = child_record.get("summary", {})
        children.append(
            {
                "path": path,
                "name": summary.get("name"),
                "description": summary.get("description"),
            }
        )
    if not children:
        raise ValueError(f"Package not found: {parent_path}")
    return children


def _get_index(index_file: str) -> OfflineSearchIndex:
    path = _resolve_path(index_file)
    key = _cache_key(str(path))
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = load_index(str(path))
    return _INDEX_CACHE[key]


def _registered_entry(registry: Dict[str, dict], doc_id: str) -> dict:
    entry = registry.get(doc_id)
    if entry is None:
        raise ValueError(f"Document is not registered: {doc_id}")
    if not entry.get("index_file"):
        raise ValueError(f"Document has no index_file registered: {doc_id}")
    return entry


def _read_registry() -> Dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {}
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid index registry: expected a JSON object.")

    # Convert the previous source-filename-keyed registry format in memory.
    registry = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        doc_id = str(entry.get("doc_id") or key)
        if "doc_id" in entry and "format" not in entry:
            entry = dict(entry)
            entry["format"] = "spec" if normalize_doc_id(doc_id) == "spec3.6" else "msl"
            entry["source_basename"] = Path(str(entry.get("source_json") or key)).name
        registry[normalize_doc_id(doc_id)] = entry
    return registry


def _write_registry(registry: Dict[str, dict]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _resolve_path(path: str) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved.resolve()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _required_str(kwargs: Dict[str, Any], key: str) -> str:
    value = kwargs.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"{key} is required and cannot be empty.")
    return str(value).strip()


def _optional_str_list(value: Any, key: str) -> Optional[List[str]]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} must be a list/tuple of strings.")
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_doc_ids(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        return [value] if value.strip() else None
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError("doc_id must be a string or a list/tuple of strings.")


def _as_bool(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
    raise ValueError(f"{key} must be a boolean value.")


def _resolve_doc_ids(values: Optional[List[str]], registry: Dict[str, dict]) -> List[str]:
    if not values:
        return list(registry)
    resolved: List[str] = []
    for item in values:
        alias = str(item or "").strip().lower()
        if not alias:
            continue
        if alias == "msl":
            doc_id = _latest_doc_for_format(registry, "msl")
        elif alias == "spec":
            doc_id = _latest_doc_for_format(registry, "spec")
        else:
            doc_id = normalize_doc_id(alias)
        if doc_id not in registry:
            raise ValueError(f"Document is not registered: {doc_id}")
        if doc_id not in resolved:
            resolved.append(doc_id)
    return resolved


def _docs_by_format(registry: Dict[str, dict], doc_format: str) -> List[str]:
    doc_ids = [doc_id for doc_id, entry in registry.items() if entry.get("format") == doc_format]
    return sorted(doc_ids, key=lambda item: _doc_sort_key(item), reverse=True)


def _latest_doc_for_format(registry: Dict[str, dict], doc_format: str) -> str:
    doc_ids = _docs_by_format(registry, doc_format)
    if not doc_ids:
        raise ValueError(f"No registered document with format={doc_format!r}.")
    return doc_ids[0]


def _doc_sort_key(doc_id: str) -> Tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)*)", doc_id)
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.group(1).split("."))


def _positive_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("Expected a positive integer.")
    number = int(value)
    if number <= 0:
        raise ValueError("Expected a positive integer.")
    return number


def _bounded_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError("Expected a numeric value.")
    number = float(value)
    if number < minimum or number > maximum:
        raise ValueError(f"Expected a value in range [{minimum}, {maximum}].")
    return number


def _cache_key(index_path: str) -> str:
    return str(Path(index_path).resolve())


def _deduplicate_candidates(candidates: List[dict]) -> List[dict]:
    result = []
    seen = set()
    for candidate in candidates:
        identity = (
            candidate.get("doc_id"),
            candidate.get("path") or candidate.get("section_path"),
        )
        if identity not in seen:
            seen.add(identity)
            result.append(candidate)
    return result


_SEARCH_SUMMARY_FIELDS = (
    "doc_id",
    "path",
    "section_path",
    "name",
    "kind",
    "description",
    "url",
    "confidence",
)


def _candidate_sort_key(candidate: dict) -> Tuple[float, float, str, str]:
    return (
        -float(candidate.get("confidence", 0.0)),
        -float(candidate.get("rank_score", 0.0)),
        str(candidate.get("path") or candidate.get("section_path") or ""),
        str(candidate.get("doc_id") or ""),
    )


def _candidate_payload(candidate: dict, debug: bool) -> dict:
    """Keep search results a pointer to a record; get returns the record body."""
    if debug:
        return candidate
    return {name: candidate[name] for name in _SEARCH_SUMMARY_FIELDS if name in candidate}


def _record_payload(full: dict, fields: Optional[List[str]]) -> Tuple[dict, List[str]]:
    """Return (payload, missing_fields).

    fields=None means the complete record; fields=[] means identifiers only.
    """
    if not isinstance(full, dict):
        return {}, []
    if fields is None:
        return dict(full), []
    payload = {field: full[field] for field in fields if field in full}
    missing = [field for field in fields if field not in full]
    return payload, missing


def _ok_response(action: str, data: dict, started: float, warnings: List[str]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "action": action,
        "status": "ok",
        "data": data,
        "error": None,
        "meta": {
            "took_ms": int((time.perf_counter() - started) * 1000),
            "warnings": list(warnings),
        },
    }


def _error_response(action: str, exc: Exception, started: float, warnings: List[str]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "action": action,
        "status": "error",
        "data": {},
        "error": {
            "code": _error_code(exc),
            "message": str(exc),
            "details": {"exception_type": type(exc).__name__},
        },
        "meta": {
            "took_ms": int((time.perf_counter() - started) * 1000),
            "warnings": list(warnings),
        },
    }


def _error_code(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "NOT_FOUND"
    if isinstance(exc, ValueError):
        message = str(exc)
        if "index.json is empty" in message:
            return "REGISTRY_EMPTY"
        if (
            "is not registered" in message
            or "No registered document" in message
            or "not found" in message.lower()
        ):
            return "NOT_FOUND"
        return "INVALID_ARGUMENT"
    if isinstance(exc, TypeError):
        return "INVALID_ARGUMENT"
    return "INTERNAL_ERROR"
