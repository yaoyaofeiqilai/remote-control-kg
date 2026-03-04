#!/usr/bin/env python3
"""Repository hygiene cleanup utility.

Deletes stale runtime artifacts and keeps only the newest handoff files.
Run with --apply to perform deletions; default is dry-run.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CleanupStats:
    files_deleted: int = 0
    dirs_deleted: int = 0
    handoff_deleted: int = 0


ROOT = Path(__file__).resolve().parents[2]
KEEP_ALWAYS = {"SESSION_HANDOFF_LATEST.md"}

ROOT_FILE_GLOBS = [
    "auto_*.jsonl",
    "auto_*.log",
    "auto_*.out.log",
    "auto_*.err.log",
    "tmp_*.jsonl",
    "tmp_*.log",
    "tmp_*.out.log",
    "tmp_*.err.log",
    "tmp_*.ps1",
    "*.pid",
    "e2e_*.log",
    "*_server.out.log",
    "*_server.err.log",
]

ROOT_DIR_GLOBS = [
    ".tmp_av*",
    "__pycache__",
]


def _delete_file(path: Path, apply: bool, stats: CleanupStats):
    if not path.exists() or not path.is_file():
        return
    if apply:
        path.unlink(missing_ok=True)
    stats.files_deleted += 1


def _delete_dir(path: Path, apply: bool, stats: CleanupStats):
    if not path.exists() or not path.is_dir():
        return
    if apply:
        shutil.rmtree(path, ignore_errors=True)
    stats.dirs_deleted += 1


def cleanup_runtime_outputs(apply: bool, stats: CleanupStats):
    for pat in ROOT_FILE_GLOBS:
        for path in ROOT.glob(pat):
            # Keep root .gitignore-managed dotfiles except pid artifacts
            if path.name in KEEP_ALWAYS:
                continue
            _delete_file(path, apply, stats)

    for pat in ROOT_DIR_GLOBS:
        for path in ROOT.glob(pat):
            _delete_dir(path, apply, stats)

    for cache_dir in ROOT.rglob("__pycache__"):
        _delete_dir(cache_dir, apply, stats)

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    for sub in ("logs", "samples", "pids", "baseline"):
        (artifacts / sub).mkdir(exist_ok=True)


def cleanup_handoffs(apply: bool, keep_count: int, stats: CleanupStats):
    handoffs = sorted(
        (
            p
            for p in ROOT.glob("SESSION_HANDOFF_*.md")
            if p.name != "SESSION_HANDOFF_LATEST.md"
        ),
        key=lambda p: p.name,
        reverse=True,
    )
    keep = set(handoffs[: max(1, int(keep_count))])
    for path in handoffs:
        if path in keep:
            continue
        if apply:
            path.unlink(missing_ok=True)
        stats.handoff_deleted += 1

    newest = next(iter(sorted(keep, key=lambda p: p.name, reverse=True)), None)
    latest_path = ROOT / "SESSION_HANDOFF_LATEST.md"
    if newest is not None:
        text = (
            "# Latest Session Pointer\n\n"
            "Current handoff file:\n\n"
            f"- `{newest.name}`\n\n"
            "Open that file first when resuming work in this repository.\n"
        )
        if apply:
            latest_path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Perform deletion. Default is dry-run.")
    parser.add_argument("--keep-handoffs", type=int, default=3, help="How many newest handoff files to keep.")
    args = parser.parse_args()

    stats = CleanupStats()
    cleanup_runtime_outputs(args.apply, stats)
    cleanup_handoffs(args.apply, args.keep_handoffs, stats)

    mode = "APPLY" if args.apply else "DRY_RUN"
    print(
        f"{mode} files_deleted={stats.files_deleted} "
        f"dirs_deleted={stats.dirs_deleted} "
        f"handoff_deleted={stats.handoff_deleted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
