import re
from typing import Iterable, List, Optional, Sequence


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
_KIND_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _split_camel_case(text: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = _split_camel_case(text)
    text = text.replace(".", " ").replace("/", " ").replace("\\", " ")
    text = text.replace("-", " ").replace(":", " ")
    text = re.sub(r"\s+", " ", text.lower()).strip()
    return text


def tokenize(text: str) -> List[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    tokens: List[str] = []
    for part in _TOKEN_PATTERN.findall(normalized):
        if not part:
            continue
        if _is_cjk(part):
            chars = list(part)
            tokens.extend(chars)
            if len(chars) > 1:
                tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))
        else:
            tokens.append(part)
    return tokens


def build_query_variants(query: str, query_variants: Optional[Iterable[str]] = None) -> List[str]:
    raw = [query]
    if query_variants:
        raw.extend(query_variants)

    dedup = []
    seen = set()
    for item in raw:
        if not item:
            continue
        norm = normalize_text(item)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        dedup.append(item)
    return dedup


def _is_cjk(text: str) -> bool:
    return all("\u4e00" <= ch <= "\u9fff" for ch in text)


def normalize_kind(kind: object, expected_kinds: Optional[Sequence[str]] = None) -> str:
    text = str(kind or "").strip().lower()
    if not text:
        return ""

    candidates = [item.strip().lower() for item in (expected_kinds or ()) if item and item.strip()]
    if not candidates:
        return text

    if text in candidates:
        return text

    tokens = _KIND_TOKEN_PATTERN.findall(text)
    for token in tokens:
        if token in candidates:
            return token

    for candidate in candidates:
        if candidate in text:
            return candidate
    return text


def kind_matches(kind: object, expected_kind: object) -> bool:
    expected = str(expected_kind or "").strip().lower()
    if not expected:
        return False
    return normalize_kind(kind, (expected,)) == expected
