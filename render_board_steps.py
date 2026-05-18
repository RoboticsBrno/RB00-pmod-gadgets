#!/usr/bin/env python3

from __future__ import annotations

import argparse
import configparser
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import uuid
ITEM_REF_PATTERNS = [
    re.compile(r'\(property\s+"Reference"\s+"([^"]+)"'),
    re.compile(r'\(fp_text\s+reference\s+"?([^"\s\)]+)"?'),
]


def extract_ref(block: str) -> str | None:
    for pattern in ITEM_REF_PATTERNS:
        match = pattern.search(block)
        if match:
            return match.group(1)
    return None


def collect_hole_refs(text: str) -> set[str]:
    refs = set()
    for start, end in top_level_footprint_spans(text):
        block = text[start:end]
        if not block.lstrip().startswith("(footprint"):
            continue
        ref = extract_ref(block)
        if ref and ref.startswith("H"):
            refs.add(ref)
    return refs


def top_level_footprint_spans(text: str):
    spans = []
    depth = 0
    in_string = False
    escape = False
    comment = False
    item_start = None

    for idx, ch in enumerate(text):
        if comment:
            if ch == "\n":
                comment = False
            continue
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == ";":
            comment = True
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "(":
            depth += 1
            if depth == 2:
                item_start = idx
            continue
        if ch == ")":
            if depth == 2 and item_start is not None:
                spans.append((item_start, idx + 1))
                item_start = None
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced board file")

    if depth != 0:
        raise ValueError("unbalanced board file")
    return spans


def strip_model_blocks(block: str) -> str:
    result = []
    i = 0
    n = len(block)

    while i < n:
        if block.startswith("(model", i):
            depth = 0
            in_string = False
            escape = False
            while i < n:
                ch = block[i]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                i += 1
            continue

        result.append(block[i])
        i += 1

    return "".join(result)


def copy_custom_model_assets(source_text: str, source_board: pathlib.Path, temp_board_path: pathlib.Path) -> None:
    model_paths = set()
    for match in re.finditer(r'\(model\s+"([^"]+)"', source_text):
        path = match.group(1)
        if path.startswith("${KIPRJMOD}") or path.startswith("/"):
            model_paths.add(path)

    if not model_paths:
        return

    dest_dir = temp_board_path.parent
    source_root = source_board.parent

    for model_path in model_paths:
        if model_path.startswith("${KIPRJMOD}"):
            relative = model_path.replace("${KIPRJMOD}", "").lstrip("/")
            src = source_root / relative
            dst = dest_dir / relative
        else:
            src = pathlib.Path(model_path)
            dst = dest_dir / src.name

        if src.exists() and src.is_file() and (not dst.exists() or src.resolve() != dst.resolve()):
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())


def filter_board(board_path: pathlib.Path, keep: set[str] | None, hide: set[str] | None, temp_dir: pathlib.Path) -> pathlib.Path:
    if not keep and not hide:
        return board_path

    text = board_path.read_text(encoding="utf-8")
    spans = top_level_footprint_spans(text)
    pieces = []
    cursor = 0
    for start, end in spans:
        block = text[start:end]
        if not block.lstrip().startswith("(footprint"):
            continue
        ref = extract_ref(block)
        strip_model = False
        if keep is not None:
            strip_model = ref is None or ref not in keep
        elif hide and ref in hide:
            strip_model = True

        pieces.append(text[cursor:start])
        pieces.append(strip_model_blocks(block) if strip_model else block)
        cursor = end
    pieces.append(text[cursor:])

    out_path = board_path.parent / f".{board_path.stem}-filtered-{uuid.uuid4().hex[:8]}.kicad_pcb"
    out_path.write_text("".join(pieces), encoding="utf-8")
    return out_path


def parse_list(value: str | None) -> set[str] | None:
    if not value:
        return None
    refs = [part.strip() for part in re.split(r"[\s,]+", value) if part.strip()]
    return set(refs) if refs else None


def expand_keep_tokens(tokens: set[str] | None, hole_refs: set[str]) -> set[str] | None:
    if tokens is None:
        return None
    expanded = set(tokens)
    if "H*" in expanded:
        expanded.remove("H*")
    expanded.update(hole_refs)
    return expanded


def make_output_name(step_index: int, step_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", step_name.strip()).strip("-").lower()
    if not slug:
        slug = f"step-{step_index:02d}"
    return f"{step_index:02d}-{slug}.png"


def load_config(config_path: pathlib.Path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = lambda option: option  # type: ignore[assignment]
    parser.read(config_path)

    defaults = {}
    for section_name in ("render", "global", "defaults", "board"):
        if parser.has_section(section_name):
            defaults.update(parser[section_name])

    steps = []
    for section in parser.sections():
        if section.lower() in {"render", "global", "defaults", "board"}:
            continue
        steps.append((section, dict(parser[section])))

    return defaults, steps


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("board_file")
    parser.add_argument("out_dir")
    parser.add_argument("--config", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--rotate", default="0,0,0")
    parser.add_argument("--zoom", default="0.75")
    parser.add_argument("--quality", default="high")
    parser.add_argument("--background", default="transparent")
    args = parser.parse_args(argv)

    board = pathlib.Path(args.board_file).resolve()
    out_dir = pathlib.Path(args.out_dir).resolve()
    config_path = pathlib.Path(args.config).resolve()

    if not board.exists():
        print(f"Board file not found: {board}", file=sys.stderr)
        return 1
    if not config_path.exists():
        return 0

    defaults, steps = load_config(config_path)
    if not steps:
        return 0

    zoom_default = defaults.get("zoom", args.zoom)
    side_default = defaults.get("side", "top")
    hole_refs = collect_hole_refs(board.read_text(encoding="utf-8"))
    base_keep = expand_keep_tokens(parse_list(defaults.get("keep")), hole_refs)
    current_keep = set(base_keep or hole_refs)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    with tempfile.TemporaryDirectory(prefix="render-steps-") as tmp:
        tmp_dir = pathlib.Path(tmp)
        for idx, (section, data) in enumerate(steps, 1):
            side = data.get("side", side_default)
            zoom = data.get("zoom", zoom_default)
            keep = parse_list(data.get("keep") or data.get("include") or data.get("refs") or data.get("footprints"))
            hide = parse_list(data.get("hide") or data.get("exclude"))
            output_name = data.get("output") or data.get("file")
            if output_name:
                output = out_dir / output_name
            else:
                output = out_dir / make_output_name(idx, section)

            if keep is not None:
                current_keep.update(expand_keep_tokens(keep, hole_refs) or set())

            temp_board = filter_board(board, set(current_keep), hide, tmp_dir)
            copy_custom_model_assets(temp_board.read_text(encoding="utf-8"), board, temp_board)
            subprocess.run(
                [
                    "kicad-cli",
                    "pcb",
                    "render",
                    "--output",
                    str(output),
                    "--width",
                    str(args.width),
                    "--height",
                    str(args.height),
                    "--side",
                    side,
                    "--rotate",
                    "0,0,0",
                    "--zoom",
                    str(zoom),
                    "--background",
                    args.background,
                    "--quality",
                    args.quality,
                    str(temp_board),
                ],
                check=True,
            )
            generated.append(output)

    if generated:
        print("Rendered step images:")
        for path in generated:
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
