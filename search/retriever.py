import time
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence

from .index_builder import OfflineSearchIndex
from .text_utils import build_query_variants, normalize_text, tokenize


def lookup_by_path(index: OfflineSearchIndex, path: str) -> Optional[dict]:
    record = index.component_by_path.get(path)
    if record is None:
        return None
    return record["full"]


def lookup_by_section_path(index: OfflineSearchIndex, section_path: str) -> Optional[dict]:
    records = index.spec_by_section_path.get(section_path)
    if not records:
        return None
    return records[0]["full"]


def search_components(
    index: OfflineSearchIndex,
    query: str,
    query_variants: Optional[Iterable[str]] = None,
    docs: Optional[Sequence[str]] = None,
    topk_per_variant: int = 20,
    final_k: int = 10,
) -> dict:
    started = time.perf_counter()
    docs_scope = _normalize_docs_scope(index, docs)

    direct = None
    if index.doc_format == "msl" and index.doc_id in docs_scope and query in index.component_by_path:
        direct = index.component_by_path[query]["summary"]
    if (
        direct is None
        and index.doc_format == "spec"
        and index.doc_id in docs_scope
        and query in index.spec_by_section_path
    ):
        direct = index.spec_by_section_path[query][0]["summary"]
    if direct is not None:
        took_ms = int((time.perf_counter() - started) * 1000)
        return {
            "query": query,
            "query_variants_used": [query],
            "docs_scope": docs_scope,
            "candidates": [_build_direct_candidate(direct)],
            "meta": {"candidate_count": 1, "took_ms": took_ms},
        }

    variants = build_query_variants(query, query_variants)
    if not variants:
        variants = [query]

    route_weights = _route_weights(index.doc_format)
    routes = tuple(route_weights.keys())
    per_route_scores: Dict[str, Dict[str, float]] = {
        route: defaultdict(float) for route in routes
    }
    evidence: Dict[str, List[dict]] = defaultdict(list)
    record_map = {record["record_key"] + "@" + record["doc_id"]: record for record in index.records}

    for variant_idx, variant in enumerate(variants):
        variant_weight = _variant_weight(variant_idx)
        tokens = tokenize(variant)
        if not tokens:
            continue
        for route in routes:
            if index.doc_id not in docs_scope or route not in index.route_indexes:
                continue
            hits = index.route_indexes[route].top_k(tokens, topk_per_variant)
            for rank, (doc_idx, score) in enumerate(hits, start=1):
                record = index.records[doc_idx]
                key = _record_identity(record)
                weighted_score = score * variant_weight
                if weighted_score > per_route_scores[route][key]:
                    per_route_scores[route][key] = weighted_score
                evidence[key].append(
                    {
                        "route": route,
                        "variant": variant,
                        "rank": rank,
                        "variant_weight": variant_weight,
                        "score": round(float(score), 6),
                        "weighted_score": round(float(weighted_score), 6),
                    }
                )

    merged_keys = set()
    for route in routes:
        merged_keys.update(per_route_scores[route].keys())

    candidates = []
    route_max = {route: _max_or_one(per_route_scores[route].values()) for route in routes}

    for key in merged_keys:
        record = record_map.get(key)
        if record is None:
            continue
        route_norm = {}
        for route in routes:
            raw = per_route_scores[route].get(key, 0.0)
            route_norm[route] = raw / route_max[route]

        rank_score = 0.0
        for route, weight in route_weights.items():
            rank_score += weight * route_norm[route]
        key_bonus = _key_bonus(record, query)
        rank_score += key_bonus
        confidence = _score_to_confidence(rank_score)

        summary = dict(record["summary"])
        summary["confidence"] = confidence
        summary["rank_score"] = round(rank_score, 6)
        summary["score_breakdown"] = {
            "route_norm": {route: round(route_norm[route], 6) for route in routes},
            "key_bonus": round(key_bonus, 6),
        }
        summary["evidence"] = sorted(
            evidence[key], key=lambda item: (item["route"], item["rank"], -item["weighted_score"])
        )
        summary["_sort_score"] = rank_score
        candidates.append(summary)

    candidates.sort(
        key=lambda item: (-item["_sort_score"], str(item.get("record_key") or ""))
    )
    selected = candidates[: max(1, final_k)]
    for item in selected:
        item.pop("_sort_score", None)

    took_ms = int((time.perf_counter() - started) * 1000)
    return {
        "query": query,
        "query_variants_used": variants,
        "docs_scope": docs_scope,
        "candidates": selected,
        "meta": {"candidate_count": len(selected), "took_ms": took_ms},
    }


def _max_or_one(values: Iterable[float]) -> float:
    best = 0.0
    for val in values:
        if val > best:
            best = val
    return best if best > 0.0 else 1.0


def _route_weights(doc_format: str) -> Dict[str, float]:
    if doc_format == "msl":
        return {
            "component_path": 0.5,
            "component_description": 0.25,
            "component_information": 0.25,
        }
    return {
        "spec_section_path": 0.4,
        "spec_content": 0.6,
    }


def _variant_weight(variant_index: int) -> float:
    return 1.0 if variant_index == 0 else 0.85


def _score_to_confidence(score: float) -> float:
    if score <= 0.0:
        return 0.0
    normalized = score / (score + 0.35)
    return max(0.0, min(1.0, round(normalized, 6)))


def _key_bonus(record: dict, query: str) -> float:
    key_name = "path" if record["record_type"] == "component" else "section_path"
    key_val = str(record["summary"].get(key_name) or "")
    q = normalize_text(query)
    p = normalize_text(key_val)
    if not q:
        return 0.0
    if q == p:
        return 0.2
    if q in p:
        return 0.05
    return 0.0


def _build_direct_candidate(summary_obj: dict) -> dict:
    summary = dict(summary_obj)
    summary["confidence"] = 1.0
    summary["rank_score"] = 1.0
    summary["score_breakdown"] = {
        "route_norm": {},
        "key_bonus": 0.0,
    }
    summary["evidence"] = [{"route": "direct_key", "variant": summary["record_key"], "rank": 1, "score": 1.0}]
    return summary


def _record_identity(record: dict) -> str:
    return record["record_key"] + "@" + record["doc_id"]


def _normalize_docs_scope(
    index: OfflineSearchIndex, docs: Optional[Sequence[str]]
) -> List[str]:
    if not docs:
        return [index.doc_id]
    normalized: List[str] = []
    for item in docs:
        name = str(item).strip().lower()
        if not name:
            continue
        if name not in normalized:
            normalized.append(name)
    if not normalized:
        raise ValueError("docs cannot be empty after normalization.")
    return normalized
