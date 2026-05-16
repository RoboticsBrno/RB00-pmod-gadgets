#!/usr/bin/env python3
"""Run KiCad DRC across all boards in a repo and filter known noise."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile
from typing import Iterable


IGNORE_TYPES = {
    "lib_footprint_mismatch",
    "lib_footprint_issues",
}

IGNORE_TEXT = re.compile(r"(silk|silkscreen|edge|courtyard.*silk|silk.*courtyard)", re.I)


def find_boards(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(root.rglob("*.kicad_pcb"))


def run_drc(board: pathlib.Path) -> dict:
    out = pathlib.Path(tempfile.gettempdir()) / f"{board.stem}_drc.json"
    subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            str(out),
            str(board),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return json.loads(out.read_text())


def violation_text(v: dict) -> str:
    parts = [str(v.get("type", "")), str(v.get("description", ""))]
    for item in v.get("items", []):
        if isinstance(item, dict):
            parts.extend(str(x) for x in item.values())
    return " ".join(parts)


def should_ignore(v: dict) -> bool:
    if v.get("type") in IGNORE_TYPES:
        return True
    return bool(IGNORE_TEXT.search(violation_text(v)))


def format_item(item: dict) -> str:
    desc = item.get("description", "")
    pos = item.get("pos")
    if pos is None:
        return desc
    return f"{desc} @ {pos}"


def print_board_report(board: pathlib.Path, data: dict) -> int:
    violations = data.get("violations", [])
    kept = [v for v in violations if not should_ignore(v)]

    print(f"=== {board.name} ===")
    print(f"Kept {len(kept)} / {len(violations)} violations after filtering silkscreen/edge + lib footprint issues")

    for idx, v in enumerate(kept, 1):
        print(f"{idx}. [{v.get('severity')}] {v.get('type')}: {v.get('description')}")
        for item in v.get("items", [])[:2]:
            if isinstance(item, dict):
                print(f"   - {format_item(item)}")
    print()
    return len(kept)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".", help="Repo root to scan")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root).resolve()
    boards = find_boards(root)
    if not boards:
        print(f"No .kicad_pcb files found under {root}", file=sys.stderr)
        return 1

    total_remaining = 0
    for board in boards:
        data = run_drc(board)
        total_remaining += print_board_report(board, data)

    return 1 if total_remaining else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
