"""Command line: `python -m fbcal build` (full run) or `build --offline` (render from stored data only)."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .pipeline import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fbcal", description="Build the Fenerbahçe calendar feeds.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="fetch sources and write .ics files + site data to the output folder")
    b.add_argument("--root", type=Path, default=Path("."))
    b.add_argument("--out", type=Path, default=Path("public"))
    b.add_argument("--offline", action="store_true", help="do not contact sources; use stored data only")
    b.add_argument("--team", action="append", help="only refresh sources for this team (repeatable)")
    b.add_argument("--report", type=Path, default=Path("build/report.md"))
    b.add_argument("--problems-file", type=Path, default=Path("build/problems.md"),
                   help="written only when a source has problems (the workflow opens an issue from it)")
    sub.add_parser("check", help="validate config and override files")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        root = getattr(args, "root", Path("."))
        config = load_config(root)
        if args.command == "check":
            from .overrides import load_overrides

            load_overrides(root / "overrides" / "manual.yaml", config)
            print("Config is valid.")
            return 0
        report = build(config, out_dir=args.out, offline=args.offline, only=args.team)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    site_dir = root / "site"
    if site_dir.is_dir():
        shutil.copytree(site_dir, args.out, dirs_exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report.to_markdown(), encoding="utf-8")
    if report.problems:
        args.problems_file.parent.mkdir(parents=True, exist_ok=True)
        args.problems_file.write_text(report.to_markdown(), encoding="utf-8")
    elif args.problems_file.exists():
        args.problems_file.unlink()
    print(report.to_markdown())
    print("Teams with changed data:", ", ".join(report.changed_teams) or "none")
    return 0
