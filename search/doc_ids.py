import re
from typing import List


DOC_MODELICA = "modelica-4.0.0"
DOC_SPEC = "spec3.6"

# Aliases are intentionally maintained in code, not supplied during build.
_ALIASES = {
    "msl": DOC_MODELICA,
    "modelica4.0.0": DOC_MODELICA,
    "msl-4.0.0": DOC_MODELICA,
    "component": DOC_MODELICA,
    "spec": DOC_SPEC,
    "spec36": DOC_SPEC,
    "spec-3.6": DOC_SPEC,
    "msl-4.1.0": "modelica-4.1.0",
}


def normalize_doc_id(value: str) -> str:
    doc = str(value or "").strip().lower()
    if not doc:
        raise ValueError("doc id cannot be empty.")
    normalized = _ALIASES.get(doc, doc)
    if normalized in (".", "..") or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", normalized):
        raise ValueError(f"Invalid doc id: {value}")
    return normalized


def normalize_doc_ids(values: List[str]) -> List[str]:
    result: List[str] = []
    for item in values:
        doc = normalize_doc_id(item)
        if doc not in result:
            result.append(doc)
    return result
