"""``flagcov`` command line.

    flagcov fetch  --api-url http://localhost:8000/api/v1/ --key ser.xxx -o environment.json
    flagcov report --env environment.json [--evaluations .flagcov/evaluations.json] [--scan src] [--format table|md|json]
    flagcov scan   src/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from flagcov import __version__
from flagcov.analyze import analyze
from flagcov.environment import EnvironmentError_, load_document
from flagcov.recorder import Recorder


def _report(args: argparse.Namespace) -> int:
    doc = load_document(args.env, args.key, args.api_url)
    evaluations = Path(args.evaluations)
    records = Recorder.load(evaluations) if evaluations.is_file() else []
    referenced = None
    if args.scan:
        from flagcov.scan import scan_paths

        referenced = scan_paths(args.scan)
    report = analyze(doc, records, referenced)
    from flagcov import report as render

    changed = set(args.only_flags.split(",")) if args.only_flags else None
    if args.diff_base:
        from flagcov.scan import changed_flags

        changed = (changed or set()) | changed_flags(args.diff_base)
    if args.out:
        render.write_all(report, args.out)
    if args.format == "md":
        print(render.markdown(report, changed))
    elif args.format == "json":
        print(json.dumps(report.to_dict(), indent=2, default=str))
    elif args.format == "stubs":
        print(render.stubs(report, changed))
    else:
        print(render.terminal(report, show_covered=not args.untested_only))
    if args.fail_untested is not None and report.untested_traffic > args.fail_untested:
        print(f"FAIL: untested production traffic {report.untested_traffic:.1f}% > {args.fail_untested}%", file=sys.stderr)
        return 2
    return 0


def _fetch(args: argparse.Namespace) -> int:
    doc = load_document(None, args.key, args.api_url)
    Path(args.output).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"Saved environment document '{doc.get('name', '')}' ({len(doc['feature_states'])} flags) to {args.output}")
    return 0


def _scan(args: argparse.Namespace) -> int:
    from flagcov.scan import scan_paths

    refs = scan_paths(args.paths)
    if args.json:
        print(json.dumps(refs, indent=2))
    else:
        for key, where in refs.items():
            print(f"{key}  ({len(where)}x)  {where[0]}")
        print(f"\n{len(refs)} flag keys found")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flagcov", description="Code coverage for feature flags (Flagsmith).")
    parser.add_argument("--version", action="version", version=f"flagcov {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def env_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--key", help="Server-side environment key (or FLAGSMITH_SERVER_KEY)")
        p.add_argument("--api-url", help="Flagsmith API URL, e.g. http://localhost:8000/api/v1/ (or FLAGSMITH_API_URL)")

    r = sub.add_parser("report", help="Report flag coverage from recorded evaluations")
    r.add_argument("--env", help="Environment document JSON file (omit to fetch from the API)")
    env_args(r)
    r.add_argument("--evaluations", default=".flagcov/evaluations.json")
    r.add_argument("--scan", action="append", help="Source path to scan for flag keys (repeatable)")
    r.add_argument("--format", choices=["table", "md", "json", "stubs"], default="table")
    r.add_argument("--only-flags", help="Comma-separated flags to focus on (e.g. flags touched by a PR)")
    r.add_argument("--diff-base", help="Focus on flags touched since this git ref (e.g. origin/main)")
    r.add_argument("--untested-only", action="store_true")
    r.add_argument("--out", help="Also write report.json, report.md, badge.svg and stubs here")
    r.add_argument("--fail-untested", type=float, help="Exit 2 if untested production traffic is above this percent")
    r.set_defaults(func=_report)

    f = sub.add_parser("fetch", help="Download the environment document from Flagsmith")
    env_args(f)
    f.add_argument("-o", "--output", default="environment.json")
    f.set_defaults(func=_fetch)

    s = sub.add_parser("scan", help="List flag keys read in source code")
    s.add_argument("paths", nargs="+")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_scan)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except EnvironmentError_ as exc:
        print(f"flagcov: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
