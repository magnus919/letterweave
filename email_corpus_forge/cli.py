"""Offline command-line planning and separately authorized dataset assembly."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from .pipeline import create_plan, export_run, run_pipeline, status_run
from .release import DatasetReleaseAuthorization, assemble_live_release


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline original email corpus tooling; fixtures are not corpus data")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "status", "export"):
        sub = subs.add_parser(name)
        sub.add_argument("--run", type=Path, required=True)
        if name == "plan":
            sub.add_argument("--seed", type=int, default=17)
            sub.add_argument("--families", type=int, dest="family_count")
            sub.add_argument("--variants-per-family", type=int, default=5)
            sub.add_argument("--requested-candidates", type=int)
            sub.add_argument("--cap-usd", default="10")
            sub.add_argument("--max-repairs", type=int, default=12)
            sub.add_argument("--max-rereviews", type=int, default=12)
            sub.add_argument("--provider-mode", choices=("fixture", "live"), default="fixture")
            sub.add_argument("--scenario-plan", type=Path)
        if name == "export":
            sub.add_argument("--out", type=Path, required=True)
    release = subs.add_parser('assemble-release', help='Offline sanitized assembly; does not publish or generate')
    release.add_argument('--runs', type=Path, nargs='+', required=True)
    release.add_argument('--out', type=Path, required=True)
    release.add_argument('--authorization', type=Path, required=True)
    release.add_argument('--qa-exclusions', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'assemble-release':
            authorization = DatasetReleaseAuthorization(**json.loads(args.authorization.read_text()))
            exclusions = json.loads(args.qa_exclusions.read_text()) if args.qa_exclusions else []
            result = assemble_live_release(args.runs, args.out, authorization=authorization, qa_exclusions=exclusions)
        elif args.command == "plan":
            result = create_plan(args.run, args.seed, family_count=args.family_count,
                                 variants_per_family=args.variants_per_family,
                                 requested_candidates=args.requested_candidates, cap_usd=args.cap_usd,
                                 max_repairs=args.max_repairs, max_rereviews=args.max_rereviews,
                                 provider_mode=args.provider_mode, scenario_plan=args.scenario_plan)
        elif args.command == "run":
            result = run_pipeline(args.run)
        elif args.command == "export":
            result = export_run(args.run, args.out)
        else:
            result = status_run(args.run)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2 if result.get("pending_attempts") or (args.command == "run" and result.get("status") != "complete") else 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
