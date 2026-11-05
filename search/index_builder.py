import json
import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .bm25 import BM25Index
from .doc_ids import DOC_MODELICA
from .text_utils import kind_matches, tokenize


@dataclass
class OfflineSearchIndex:
    version: str
    doc_id: str
    doc_format: str
    source_docs: Dict[str, str]
    built_at_utc: str
    records: List[dict]
    component_by_path: Dict[str, dict]
    spec_by_section_path: Dict[str, List[dict]]
    route_indexes: Dict[str, BM25Index]


def build_index_from_json(input_json_path: str) -> OfflineSearchIndex:
    return build_index_from_documents(
        [{"doc_id": DOC_MODELICA, "format": "msl", "path": input_json_path}]
    )


def build_index_from_documents(documents: Sequence[dict]) -> OfflineSearchIndex:
    if not documents:
        raise ValueError("documents cannot be empty.")

    records: List[dict] = []
    component_by_path: Dict[str, dict] = {}
    spec_by_section_path: Dict[str, List[dict]] = {}
    source_docs: Dict[str, str] = {}
    index_doc_id = ""
    index_format = ""

    for doc in documents:
        doc_id = str(doc.get("doc_id") or "").strip()
        doc_format = str(doc.get("format") or "").strip().lower()
        path = str(doc.get("path") or "").strip()
        if not doc_id or not path or doc_format not in ("msl", "spec"):
            raise ValueError("Each document must include doc_id, path, and format msl|spec.")
        if index_doc_id and (index_doc_id != doc_id or index_format != doc_format):
            raise ValueError("One index file can contain exactly one doc_id and format.")
        index_doc_id = doc_id
        index_format = doc_format
        source_docs[doc_id] = path

        src = Path(path)
        with src.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"Input JSON must be a list: {path}")

        if doc_format == "msl":
            _append_component_records(records, component_by_path, data, doc_id)
        elif doc_format == "spec":
            _append_spec_records(records, spec_by_section_path, data, doc_id)

    route_corpora = (
        {
            "component_path": [],
            "component_description": [],
            "component_information": [],
        }
        if index_format == "msl"
        else {
            "spec_section_path": [],
            "spec_content": [],
        }
    )
    for record in records:
        if record["record_type"] == "component":
            route_corpora["component_path"].append(tokenize(record["summary"].get("path", "")))
            route_corpora["component_description"].append(
                tokenize(record["summary"].get("description", ""))
            )
            route_corpora["component_information"].append(
                tokenize(record["summary"].get("information", ""))
            )
        else:
            route_corpora["spec_section_path"].append(
                tokenize(record["summary"].get("section_path", ""))
            )
            route_corpora["spec_content"].append(tokenize(record["summary"].get("content", "")))

    route_indexes = {route: BM25Index(tokens) for route, tokens in route_corpora.items()}

    return OfflineSearchIndex(
        version="v2-offline-single-doc",
        doc_id=index_doc_id,
        doc_format=index_format,
        source_docs=source_docs,
        built_at_utc=datetime.now(timezone.utc).isoformat(),
        records=records,
        component_by_path=component_by_path,
        spec_by_section_path=spec_by_section_path,
        route_indexes=route_indexes,
    )


def save_index(index: OfflineSearchIndex, output_path: str) -> None:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_index(index_path: str) -> OfflineSearchIndex:
    src = Path(index_path)
    with src.open("rb") as f:
        idx = pickle.load(f)
    if not isinstance(idx, OfflineSearchIndex):
        raise TypeError("Invalid index file content.")
    required_attrs = (
        "version",
        "doc_id",
        "doc_format",
        "source_docs",
        "records",
        "component_by_path",
        "spec_by_section_path",
        "route_indexes",
    )
    missing = [name for name in required_attrs if not hasattr(idx, name)]
    if missing:
        raise ValueError(
            "Index format is outdated and incompatible with current code. "
            f"Missing fields: {', '.join(missing)}. "
            "Please rebuild this index using the current build command."
        )
    return idx


def _interface_items(row: dict) -> List[dict]:
    # Dumps produced before the rename still use "components" for the same list.
    value = row.get("interface")
    if value is None:
        value = row.get("components")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _extract_parameter_summary(row: dict, max_count: int = 8) -> List[dict]:
    summary: List[dict] = []
    for item in _interface_items(row):
        if not kind_matches(item.get("kind"), "parameter"):
            continue
        summary.append(
            {
                "name": item.get("name"),
                "type": item.get("type"),
                "unit": item.get("unit"),
                "description": item.get("description"),
            }
        )
        if len(summary) >= max_count:
            break
    return summary


def _append_component_records(
    records: List[dict],
    component_by_path: Dict[str, dict],
    data: Iterable[dict],
    doc_id: str,
) -> None:
    seen_paths = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip()
        if not path:
            continue
        if path in seen_paths:
            raise ValueError(f"Duplicate path in {doc_id}: {path}")
        seen_paths.add(path)
        if path in component_by_path:
            raise ValueError(f"Cross-document duplicate component path: {path}")

        name = str(row.get("name") or "")
        description = str(row.get("description") or "")
        information = str(row.get("information") or "")
        summary = {
            "doc_id": doc_id,
            "record_type": "component",
            "record_key": path,
            "path": path,
            "name": name,
            "kind": row.get("kind"),
            "description": description,
            "information": information,
            "parameter_summary": _extract_parameter_summary(row),
        }
        record = {"doc_id": doc_id, "record_type": "component", "record_key": path, "summary": summary, "full": row}
        records.append(record)
        component_by_path[path] = record


def _append_spec_records(
    records: List[dict],
    spec_by_section_path: Dict[str, List[dict]],
    data: Iterable[dict],
    doc_id: str,
) -> None:
    seen_sections = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        section_path = str(row.get("section_path") or "").strip()
        if not section_path:
            continue
        if section_path in seen_sections:
            raise ValueError(f"Duplicate section_path in {doc_id}: {section_path}")
        seen_sections.add(section_path)

        content = str(row.get("content") or "")
        summary = {
            "doc_id": doc_id,
            "record_type": "spec_section",
            "record_key": section_path,
            "section_path": section_path,
            "url": row.get("url"),
            "content": content,
        }
        record = {
            "doc_id": doc_id,
            "record_type": "spec_section",
            "record_key": section_path,
            "summary": summary,
            "full": row,
        }
        records.append(record)
        if section_path not in spec_by_section_path:
            spec_by_section_path[section_path] = []
        spec_by_section_path[section_path].append(record)
