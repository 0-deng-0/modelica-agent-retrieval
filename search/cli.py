import argparse
import json
import sys
from typing import List

from .api import run_search_api


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Modelica document search CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build one index for one JSON document.")
    build_parser.add_argument("--input", required=True, help="Source JSON path.")
    build_parser.add_argument("--format", required=True, choices=["msl", "spec"])
    build_parser.add_argument("--doc-id", required=True, help="Index identity, e.g. modelica-4.1.0.")
    build_parser.add_argument("--desc", default="", help="Optional description stored in index.json.")
    build_parser.add_argument("--pretty", action="store_true")

    search_parser = subparsers.add_parser("search", help="Search registered documents.")
    search_parser.add_argument("--doc", action="append", default=[], help="Optional doc id/alias; repeatable.")
    search_parser.add_argument("--query", required=True, help="Main query text.")
    search_parser.add_argument("--variants-json", default="", help="Optional JSON array of query variants.")
    search_parser.add_argument("--variant", action="append", default=[], help="Query variant; repeatable.")
    search_parser.add_argument("--final-k", type=int, default=10)
    search_parser.add_argument("--min-confidence", type=float, default=0.15)
    search_parser.add_argument(
        "--debug", action="store_true", help="Include evidence/score breakdown and record text."
    )
    search_parser.add_argument("--pretty", action="store_true")

    get_parser = subparsers.add_parser("get", help="Get records by path or section_path.")
    get_parser.add_argument("--doc", default="", help="Optional doc id/alias.")
    get_parser.add_argument("--path", action="append", default=[], help="Component path; repeatable.")
    get_parser.add_argument(
        "--section-path", action="append", default=[], help="Spec section_path; repeatable."
    )
    get_parser.add_argument(
        "--field",
        action="append",
        default=None,
        help="Optional field name to return; repeatable. Omit for the full record.",
    )
    get_parser.add_argument(
        "--ids-only",
        action="store_true",
        help="Return only status/doc_id/key, without record fields.",
    )
    get_parser.add_argument("--pretty", action="store_true")

    children_parser = subparsers.add_parser(
        "list-children", help="List the direct children of an MSL package."
    )
    children_parser.add_argument("--doc", default="", help="Optional doc id/alias.")
    children_parser.add_argument("--parent", default="", help="Package path; defaults to Modelica.")
    children_parser.add_argument("--kind", default="", help="Optional kind filter, e.g. block.")
    children_parser.add_argument("--pretty", action="store_true")

    list_parser = subparsers.add_parser("list-docs", help="List registered searchable documents.")
    list_parser.add_argument("--pretty", action="store_true")

    health_parser = subparsers.add_parser(
        "health", help="Report registry status without listing documents."
    )
    health_parser.add_argument("--pretty", action="store_true")

    args = parser.parse_args()
    if args.command == "build":
        payload = run_search_api(
            "build",
            input_json_path=args.input,
            format=args.format,
            doc_id=args.doc_id,
            desc=args.desc,
        )
        _emit_json(payload, args.pretty)
        raise SystemExit(0 if payload.get("status") == "ok" else 1)

    if args.command == "search":
        variants = _parse_variants(args.variants_json)
        variants.extend(args.variant)
        payload = run_search_api(
            "search",
            doc_id=args.doc,
            query=args.query,
            query_variants=variants,
            final_k=args.final_k,
            min_confidence=args.min_confidence,
            debug=args.debug,
        )
        _emit_json(payload, args.pretty)
        raise SystemExit(0 if payload.get("status") == "ok" else 1)

    if args.command == "get":
        if args.ids_only:
            fields = []
        else:
            fields = args.field
        payload = run_search_api(
            "get",
            doc_id=args.doc,
            paths=args.path,
            section_paths=args.section_path,
            fields=fields,
        )
        _emit_json(payload, args.pretty)
        raise SystemExit(0 if payload.get("status") == "ok" else 1)

    if args.command == "list-children":
        payload = run_search_api(
            "list-children",
            doc_id=args.doc,
            parent=args.parent,
            kind=args.kind,
        )
        _emit_json(payload, args.pretty)
        raise SystemExit(0 if payload.get("status") == "ok" else 1)

    if args.command == "list-docs":
        payload = run_search_api("list-docs")
        _emit_json(payload, args.pretty)
        raise SystemExit(0 if payload.get("status") == "ok" else 1)

    if args.command == "health":
        payload = run_search_api("health")
        _emit_json(payload, args.pretty)
        raise SystemExit(0 if payload.get("status") == "ok" else 1)

    raise ValueError(f"Unsupported command: {args.command!r}")


def _parse_variants(text: str) -> List[str]:
    if not text:
        return []
    value = json.loads(text)
    if not isinstance(value, list):
        raise ValueError("--variants-json must be a JSON array.")
    return [str(item).strip() for item in value if str(item).strip()]


def _emit_json(payload: dict, pretty: bool) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None)
    sys.stdout.buffer.write((text + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
