#!/usr/bin/env python3
"""
Generate Czech assembly step descriptions from render.steps and update manual.md.

Reads the render.steps config and .kicad_pcb component values for each board,
builds a prompt for each assembly step, calls an LLM, and inserts the resulting
descriptions into the board's manual.md.

Usage:
    python generate_descriptions.py pmod/DPad
    python generate_descriptions.py pmod/DPad pmod/joystick
    python generate_descriptions.py --all
    python generate_descriptions.py --all --provider gemini --api-key YOUR_KEY
    python generate_descriptions.py --all --provider anthropic --anthropic-key YOUR_KEY
    python generate_descriptions.py --all --model jobautomation/OpenEuroLLM-Czech:latest --lang cs
    python generate_descriptions.py pmod/DPad --deepl-key YOUR_KEY
    python generate_descriptions.py pmod/DPad --local-translate
    python generate_descriptions.py pmod/DPad --dry-run
    python generate_descriptions.py pmod/DPad --force
    python generate_descriptions.py --all --readme --provider anthropic --anthropic-key YOUR_KEY
    python generate_descriptions.py pmod/DPad --readme --force
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

BOARD_ROOT = pathlib.Path("pmod")
BLACKLIST = {"assets", "template"}

IMG_RE = re.compile(r'!\[[^\]]*\]\(assets/steps/(\d{2}-[^)]+\.png)\)')


# ---------------------------------------------------------------------------
# KiCad PCB parsing
# ---------------------------------------------------------------------------

def _iter_footprint_blocks(board_dir: pathlib.Path):
    """Yield (ref, value, footprint_lib_name) tuples from a KiCad PCB file."""
    pcb_files = [
        f for f in (board_dir / "KiCad").glob("*.kicad_pcb")
        if not f.name.startswith(".")
    ]
    if not pcb_files:
        return

    text = pcb_files[0].read_text(encoding="utf-8")
    depth = 0
    in_str = False
    esc = False
    block_start: int | None = None

    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "(":
            depth += 1
            if depth == 2:
                block_start = i
        elif ch == ")":
            if depth == 2 and block_start is not None:
                block = text[block_start: i + 1]
                if block.lstrip().startswith("(footprint"):
                    fp_m = re.match(r'\(footprint\s+"([^"]+)"', block.lstrip())
                    ref_m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
                    val_m = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
                    if ref_m and val_m:
                        yield (
                            ref_m.group(1),
                            val_m.group(1),
                            fp_m.group(1) if fp_m else "",
                        )
                block_start = None
            depth -= 1


def extract_component_values(board_dir: pathlib.Path) -> dict[str, str]:
    return {ref: val for ref, val, _ in _iter_footprint_blocks(board_dir)}


def extract_component_footprints(board_dir: pathlib.Path) -> dict[str, str]:
    """Return ref → footprint library:name string for all components."""
    return {ref: fp for ref, _, fp in _iter_footprint_blocks(board_dir)}


_FOOTPRINT_CONNECTOR_CS: dict[str, str] = {
    "jst_sh": "JST SH konektor",
    "jst_xh": "JST XH konektor",
    "jst_ph": "JST PH konektor",
    "jst_gh": "JST GH konektor",
    "jst_pa": "JST PA konektor",
    "jst_zh": "JST ZH konektor",
    "pinheader_2.54": "pinový konektor 2.54 mm",
    "pinheader_1.27": "pinový konektor 1.27 mm",
    "pinsocket_2.54": "pinová lišta 2.54 mm",
    "pinsocket_1.27": "pinová lišta 1.27 mm",
}

_FOOTPRINT_CONNECTOR_EN: dict[str, str] = {
    "jst_sh": "JST SH connector",
    "jst_xh": "JST XH connector",
    "jst_ph": "JST PH connector",
    "jst_gh": "JST GH connector",
    "jst_pa": "JST PA connector",
    "jst_zh": "JST ZH connector",
    "pinheader_2.54": "pin header 2.54 mm",
    "pinheader_1.27": "pin header 1.27 mm",
    "pinsocket_2.54": "pin socket 2.54 mm",
    "pinsocket_1.27": "pin socket 1.27 mm",
}


def _connector_type_from_footprint(fp: str, lang: str = "cs") -> str | None:
    fp_lower = fp.lower()
    table = _FOOTPRINT_CONNECTOR_CS if lang == "cs" else _FOOTPRINT_CONNECTOR_EN
    for key, label in table.items():
        if key in fp_lower:
            return label
    return None


# ---------------------------------------------------------------------------
# render.steps parsing
# ---------------------------------------------------------------------------

def _parse_refs(value: str) -> set[str]:
    if not value:
        return set()
    return {p.strip() for p in re.split(r"[\s,]+", value) if p.strip()}


def _step_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-").lower()
    return slug or "step"


def parse_steps(
    steps_path: pathlib.Path,
) -> tuple[dict[str, str], list[tuple[int, str, set[str], str]]]:
    """Return (defaults, [(idx, section_name, new_refs, side), ...])."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = lambda option: option  # type: ignore[assignment]
    parser.read(steps_path)

    defaults: dict[str, str] = {}
    for sec in ("render", "global", "defaults", "board"):
        if parser.has_section(sec):
            defaults.update(parser[sec])

    default_side = defaults.get("side", "top")
    base_refs = _parse_refs(defaults.get("keep", "")) - {"H*"}

    current = set(base_refs)
    steps = []
    for idx, section in enumerate(
        (s for s in parser.sections() if s.lower() not in {
         "render", "global", "defaults", "board"}),
        start=1,
    ):
        data = dict(parser[section])
        keep_raw = (
            data.get("keep")
            or data.get("include")
            or data.get("refs")
            or data.get("footprints")
            or ""
        )
        new_raw = _parse_refs(keep_raw) - {"H*"}
        previous = set(current)
        current.update(new_raw)
        new_refs = current - previous
        side = data.get("side", default_side)
        steps.append((idx, section, new_refs, side))

    return defaults, steps


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

# Component type labels derived from reference designator prefix (longest match first)
_REF_TYPE: dict[str, str] = {
    "PMOD": "PMOD connector",
    "LED":  "LED",
    "SW":   "button",
    "JP":   "jumper",
    "FB":   "ferrite bead",
    "R":    "resistor",
    "C":    "capacitor",
    "L":    "inductor",
    "D":    "diode",
    "Q":    "transistor",
    "U":    "IC",
    "J":    "connector",
    "Y":    "crystal",
}


def _component_type(ref: str) -> str | None:
    for prefix in sorted(_REF_TYPE, key=len, reverse=True):
        if ref.upper().startswith(prefix):
            return _REF_TYPE[prefix]
    return None


_REF_TYPE_CS: dict[str, str] = {
    "PMOD": "PMOD konektor",
    "LED":  "LED",
    "BZ":   "bzučák",
    "IR":   "IR senzor",
    "MK":   "mikrofon",
    "RV":   "potenciometr",
    "SW":   "tlačítko",
    "JP":   "jumper",
    "FB":   "feritová perla",
    "TR":   "transformátor",
    "R":    "rezistor",
    "C":    "kondenzátor",
    "L":    "induktor",
    "D":    "dioda",
    "Q":    "tranzistor",
    "J":    "konektor",
    "Y":    "krystal",
}

_REF_TYPE_CS_PLURAL: dict[str, str] = {
    "PMOD": "PMOD konektory",
    "LED":  "LED diody",
    "BZ":   "bzučáky",
    "IR":   "IR senzory",
    "MK":   "mikrofony",
    "RV":   "potenciometry",
    "SW":   "tlačítka",
    "JP":   "jumpery",
    "FB":   "feritové perly",
    "TR":   "transformátory",
    "R":    "rezistory",
    "C":    "kondenzátory",
    "L":    "induktory",
    "D":    "diody",
    "Q":    "tranzistory",
    "J":    "konektory",
    "Y":    "krystaly",
}

# Polarized / orientation-sensitive types: prefix → (admonition_level, cs_message)
_POLARIZED: dict[str, tuple[str, str]] = {
    "LED": ("danger",  "LED je polarizovaná — zkontrolujte orientaci anody (+) a katody (−) před pájením."),
    "D":   ("danger",  "Dioda je polarizovaná — zkontrolujte orientaci anody a katody před pájením."),
    "Q":   ("warning", "Tranzistor musí být správně orientovaný — zkontrolujte označení pouzdra."),
#    "U":   ("warning", "Zkontrolujte správnou orientaci součástky podle orientační značky nebo pinu 1 na pouzdře."),
}


def _component_type_cs(ref: str) -> str | None:
    for prefix in sorted(_REF_TYPE_CS, key=len, reverse=True):
        if ref.upper().startswith(prefix):
            return _REF_TYPE_CS[prefix]
    return None


def _step_header_label(
    new_refs: set[str],
    target_lang: str,
    extra_type_labels: dict[str, str] | None = None,
) -> str:
    """Short descriptive label for a step header: 'Rezistory', 'Dioda', 'Kondenzátor, tlačítko'."""
    if not new_refs:
        return "Prázdná deska" if target_lang == "cs" else "Empty board"

    if target_lang != "cs":
        _key = lambda r: (re.match(r"[A-Za-z]+", r).group() if re.match(r"[A-Za-z]+", r) else r,
                          int(re.search(r"\d+$", r).group()) if re.search(r"\d+$", r) else 0)
        return _compact_refs(sorted(new_refs, key=_key))

    # For refs with LLM-generated labels, use those directly (deduplicated, order-preserving).
    if extra_type_labels:
        seen: set[str] = set()
        llm_parts = []
        for r in sorted(new_refs):
            label = extra_type_labels.get(r)
            if label and label not in seen:
                llm_parts.append(label)
                seen.add(label)
        known_refs = {r for r in new_refs if r not in extra_type_labels}
    else:
        llm_parts = []
        known_refs = new_refs

    counts: dict[str, int] = {}
    for ref in known_refs:
        prefix = next(
            (p for p in sorted(_REF_TYPE_CS, key=len, reverse=True) if ref.upper().startswith(p)),
            None,
        )
        if prefix:
            counts[prefix] = counts.get(prefix, 0) + 1

    parts = []
    for prefix, count in counts.items():
        name = ((_REF_TYPE_CS_PLURAL if count > 1 else _REF_TYPE_CS).get(prefix) or prefix)
        parts.append(name[0].upper() + name[1:])

    all_parts = llm_parts + parts
    if not all_parts:
        # No type label known — fall back to the ref designators themselves
        _key = lambda r: (re.match(r"[A-Za-z]+", r).group() if re.match(r"[A-Za-z]+", r) else r,
                          int(re.search(r"\d+$", r).group()) if re.search(r"\d+$", r) else 0)
        return _compact_refs(sorted(new_refs, key=_key))
    return ", ".join(p[0].upper() + p[1:] for p in all_parts)


_SI_SYMBOL = {"m": "m", "u": "µ", "µ": "µ", "n": "n", "p": "p"}

# Unit inferred from reference prefix when the value has only an SI prefix (e.g. "100n", "10u")
_REF_UNIT: dict[str, str] = {"R": "Ω", "C": "F", "L": "H", "FB": "H"}


def _ref_unit(ref: str) -> str | None:
    for prefix in sorted(_REF_UNIT, key=len, reverse=True):
        if ref.upper().startswith(prefix):
            return _REF_UNIT[prefix]
    return None


def _normalize_value(value: str, ref: str = "") -> str:
    """Convert KiCad value strings to human-readable units (10k → 10 kΩ, 1uF → 1 µF)."""
    v = value.strip()

    # SI prefix + unit letter present (1uF, 100nF, 10pH, 2.2uH)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([munpµ])([FHΩ])$", v, re.IGNORECASE)
    if m:
        num, prefix, unit = m.group(1), m.group(2).lower(), m.group(3)
        return f"{num} {_SI_SYMBOL.get(prefix, prefix)}{unit}"

    # SI prefix only, no unit letter (100n, 10u) — infer unit from ref
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([munpµ])$", v, re.IGNORECASE)
    if m:
        num, prefix = m.group(1), m.group(2).lower()
        unit = _ref_unit(ref) or "F"
        return f"{num} {_SI_SYMBOL.get(prefix, prefix)}{unit}"

    # Resistance with explicit k/M prefix, no unit letter (10k, 4.7K, 1M)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kKM])$", v)
    if m:
        num, prefix = m.group(1), m.group(2)
        return f"{num} {'kΩ' if prefix.lower() == 'k' else 'MΩ'}"

    # Resistance with SI prefix + R suffix (4.7kR, 10KR, 1MR)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kKM])[Rr]$", v)
    if m:
        num, prefix = m.group(1), m.group(2)
        return f"{num} {'kΩ' if prefix.lower() == 'k' else 'MΩ'}"

    # Resistance with explicit R suffix (100R, 470R)
    m = re.match(r"^(\d+(?:\.\d+)?)\s*[Rr]$", v)
    if m:
        return f"{m.group(1)} Ω"

    return v


def _format_component(ref: str, component_values: dict[str, str]) -> str:
    raw_val = component_values.get(ref, "")
    type_hint = _component_type(ref)

    # "IC" is too generic — part number already identifies the component better
    if type_hint == "IC":
        type_hint = None

    # Skip KiCad internal identifiers (contain underscore or are pure letters)
    val = ""
    if raw_val and "_" not in raw_val and re.search(r"\d", raw_val):
        val = _normalize_value(raw_val, ref)

    if val and type_hint:
        return f"**{ref}** ({type_hint}, **{val}**)"
    if val:
        return f"**{ref}** (**{val}**)"
    if type_hint:
        return f"**{ref}** ({type_hint})"
    return f"**{ref}**"


def _polarization_admonition(ref: str, component_values: dict[str, str]) -> str | None:
    """Return an MkDocs admonition for polarized/oriented refs, or None."""
    for prefix in sorted(_POLARIZED, key=len, reverse=True):
        if ref.upper().startswith(prefix):
            level, msg = _POLARIZED[prefix]
            type_cs = _component_type_cs(ref)
            raw_val = component_values.get(ref, "")
            val = _normalize_value(raw_val, ref) if raw_val and "_" not in raw_val and re.search(r"\d", raw_val) else ""
            if val and type_cs:
                label = f"**{ref}** ({type_cs}, **{val}**)"
            elif val:
                label = f"**{ref}** (**{val}**)"
            elif type_cs:
                label = f"**{ref}** ({type_cs})"
            else:
                label = f"**{ref}**"
            return f'!!! {level} "Pozor"\n    {label} — {msg}'
    return None


def _compact_refs(refs: list[str]) -> str:
    """Collapse runs of ≥3 consecutive same-prefix refs: [R1,R2,R3,R4] → 'R1–R4'."""
    result: list[str] = []
    i = 0
    while i < len(refs):
        m = re.match(r"([A-Za-z]+)(\d+)$", refs[i])
        if not m:
            result.append(refs[i])
            i += 1
            continue
        prefix, start_num = m.group(1), int(m.group(2))
        j = i + 1
        while j < len(refs):
            mj = re.match(r"([A-Za-z]+)(\d+)$", refs[j])
            if mj and mj.group(1) == prefix and int(mj.group(2)) == start_num + (j - i):
                j += 1
            else:
                break
        if j - i >= 3:
            result.append(f"{prefix}{start_num}–{prefix}{start_num + j - i - 1}")
            i = j
        else:
            result.append(refs[i])
            i += 1
    return ", ".join(result)


# Pre-translated Czech hints for common section names used in render.steps.
_SECTION_HINT_CS: dict[str, str] = {
    "encoder":       "rotační enkodér",
    "rotary-encoder": "rotační enkodér",
    "thermometer":   "teploměrný senzor",
    "temperature":   "teploměrný senzor",
    "gyro":          "gyroskop",
    "gyroscope":     "gyroskop",
    "accelerometer": "akcelerometr",
    "rfid":          "RFID čtečka",
    "rtc":           "hodiny reálného času",
    "motor":         "řadič motoru",
    "motor-driver":  "řadič motoru",
    "mic":           "mikrofon",
    "microphone":    "mikrofon",
    "buzzer":        "bzučák",
    "joystick":      "joystick",
    "amplifier":     "zesilovač signálu",
    "opamp":         "operační zesilovač",
    "display":       "displej",
    "oled":          "OLED displej",
}


def generate_unknown_type_labels(
    unknown_refs: dict[str, str],
    generate_fn,
    target_lang: str = "cs",
    ref_sections: dict[str, str] | None = None,
) -> dict[str, str]:
    """Ask the LLM for short descriptive type labels for components with no known type.

    unknown_refs maps ref → part number, e.g. {"U1": "DS18B20"}.
    ref_sections maps ref → render.steps section name, e.g. {"U1": "thermometer"}.
    Returns a dict of ref → label, e.g. {"U1": "teploměrný senzor"}.
    """
    if not unknown_refs:
        return {}

    def _line(ref: str, val: str) -> str:
        section = (ref_sections or {}).get(ref, "")
        if section:
            key = re.sub(r"[-_\s]+", "-", section.lower()).strip("-")
            hint = _SECTION_HINT_CS.get(key) or _SECTION_HINT_CS.get(section.lower()) or section
            return f"{ref}: {val} — jedná se o '{hint}'"
        return f"{ref}: {val}"

    lines = "\n".join(_line(ref, val) for ref, val in sorted(unknown_refs.items()))

    if target_lang == "cs":
        prompt = (
            "Jsi expert na elektroniku. Pro každou součástku níže napiš POUZE krátký český název "
            "typu (2–3 slova), který přesně popisuje, co součástka dělá. "
            "Pokud je za pomlčkou uveden název kroku, použij ho jako vodítko — ale do výstupu ho nepiš.\n\n"
            f"{lines}\n\n"
            "Výstup: přesně jeden řádek na součástku ve formátu 'OZNAČENÍ: český název'.\n"
            "Bez dalších komentářů, bez vysvětlování, bez anglických slov."
        )
    else:
        prompt = (
            "You are an electronics expert. For each component below, write ONLY a short English "
            "type name (2–3 words) that precisely describes what the component does. "
            "If a step name is given after a dash, use it as a guide — but do not include it in the output.\n\n"
            f"{lines}\n\n"
            "Output: exactly one line per component in the format 'REF: type name'.\n"
            "No other commentary."
        )

    try:
        response = generate_fn(prompt)
        labels: dict[str, str] = {}
        for line in response.strip().splitlines():
            if ":" in line:
                ref, _, label = line.partition(":")
                ref = ref.strip().upper()
                label = label.strip().strip("*").strip()
                if ref in unknown_refs and label:
                    labels[ref] = label
        return labels
    except Exception:
        return {}


def generate_bom_section(
    all_refs: set[str],
    component_values: dict[str, str],
    target_lang: str,
    extra_type_labels: dict[str, str] | None = None,
) -> str:
    """Build a markdown BOM table, grouped by component type and value."""
    if target_lang == "cs":
        heading = "## Součástky"
        col_des, col_type, col_val, col_qty = "Označení", "Typ", "Hodnota", "Počet"
    else:
        heading = "## Components"
        col_des, col_type, col_val, col_qty = "Designator", "Type", "Value", "Qty"

    groups: dict[tuple[str, str], list[str]] = {}
    for ref in sorted(all_refs):
        type_hint = (
            (extra_type_labels or {}).get(ref)
            or (_component_type_cs(ref) if target_lang == "cs" else _component_type(ref))
            or "—"
        )
        raw_val = component_values.get(ref, "")
        if raw_val and "_" not in raw_val and re.search(r"\d", raw_val):
            val = _normalize_value(raw_val, ref)
            # Append unit for plain integers that normalize didn't expand (e.g. "100" → "100 Ω")
            if re.match(r"^\d+(\.\d+)?$", val) and (unit := _ref_unit(ref)):
                val = f"{val} {unit}"
        else:
            val = "—"
        groups.setdefault((type_hint, val), []).append(ref)

    def _ref_sort_key(r: str) -> tuple[str, int]:
        m = re.match(r"([A-Za-z]+)(\d*)", r)
        return (m.group(1), int(m.group(2)) if m and m.group(2) else 0) if m else (r, 0)

    rows = []
    for (type_hint, val), refs in sorted(groups.items()):
        qty = str(len(refs))
        rows.append((_compact_refs(sorted(refs, key=_ref_sort_key)), type_hint, val, qty))

    w0 = max(len(col_des), *(len(r[0]) for r in rows))
    w1 = max(len(col_type), *(len(r[1]) for r in rows))
    w2 = max(len(col_val), *(len(r[2]) for r in rows))
    w3 = max(len(col_qty), *(len(r[3]) for r in rows))

    def _row(a: str, b: str, c: str, d: str) -> str:
        return f"| {a:<{w0}} | {b:<{w1}} | {c:<{w2}} | {d:<{w3}} |"

    lines = [
        heading, "",
        _row(col_des, col_type, col_val, col_qty),
        f"| {'-' * w0} | {'-' * w1} | {'-' * w2} | {'-' * w3} |",
        *(_row(*r) for r in rows),
    ]
    return "\n".join(lines)


def build_prompt(
    board_name: str,
    step_name: str,
    new_refs: set[str],
    component_values: dict[str, str],
    side: str,
    target_lang: str = "en",
    extra_type_labels: dict[str, str] | None = None,
) -> str:
    side_en = "top side" if side == "top" else "bottom side"

    if not new_refs:
        step_context = (
            "Step: empty board\n"
            "Components added in this step: none — this is the starting state before assembly begins."
        )
    else:
        def _rsort(r: str) -> tuple[str, int]:
            m = re.match(r"([A-Za-z]+)(\d*)", r)
            return (m.group(1), int(m.group(2)) if m and m.group(2) else 0) if m else (r, 0)

        # Group refs by (type, value) so identical components are listed once compactly.
        grp: dict[tuple[str, str], list[str]] = {}
        for ref in new_refs:
            raw_val = component_values.get(ref, "")
            val = _normalize_value(raw_val, ref) \
                if raw_val and "_" not in raw_val and re.search(r"\d", raw_val) else ""
            type_hint = (extra_type_labels or {}).get(ref)
            if type_hint is None:
                type_hint = _component_type_cs(ref) if target_lang == "cs" \
                    else _component_type(ref)
                if type_hint == "IC":
                    type_hint = None
            grp.setdefault((type_hint or "", val), []).append(ref)

        conj = " a " if target_lang == "cs" else " and "
        parts = []
        for (type_hint, val), refs in sorted(grp.items(),
                key=lambda x: _rsort(min(x[1], key=_rsort))):
            srt = sorted(refs, key=_rsort)
            bold = [f"**{r}**" for r in srt]
            if len(bold) == 1:
                ref_str = bold[0]
            else:
                ref_str = ", ".join(bold[:-1]) + conj + bold[-1]
            if len(srt) == 1:
                # Single ref — include type name for full context
                if val and type_hint:
                    parts.append(f"{ref_str} ({type_hint}, **{val}**)")
                elif val:
                    parts.append(f"{ref_str} (**{val}**)")
                elif type_hint:
                    parts.append(f"{ref_str} ({type_hint})")
                else:
                    parts.append(ref_str)
            else:
                # Multiple identical refs — just value once at the end
                if val:
                    parts.append(f"{ref_str} (**{val}**)")
                elif type_hint:
                    parts.append(f"{ref_str} ({type_hint})")
                else:
                    parts.append(ref_str)
        step_context = (
            f"Step: {step_name}\n"
            f"Components added in this step: {', '.join(parts)}\n"
            f"Board side shown in the image: {side_en}"
        )

    if target_lang == "cs":
        lang_instructions = (
            "Napište JEDNU větu v češtině popisující tento montážní krok. Jedná se o pájení součástek na DPS.\n"
            "- Přirozená čeština, vykejte čtenáři\n"
            "- Jedna přímá věta: co pájet, kam to jde — nic víc\n"
            "- Typ součástky je uveden v závorce za označením — použijte PŘESNĚ tento název; "
            "nikdy nepište 'integrovaný obvod' ani 'IC'\n"
            "- Označení součástek a hodnoty přepište tučně přesně dle zadání výše\n"
            "- Střídejte slovesa: zapájejte / přiletujte / osadťe a zapájejte / připájejte / zaletujte\n"
            "- Každý krok musí znít jinak než ostatní — měňte sloveso i strukturu věty\n"
            "- ZAKÁZANÁ slova a fráze (nesmí se objevit nikde ve výstupu):\n"
            "  'přilepte', 'přilepený', 'nalepit', 'nalepte',\n"
            "  'pečlivě připájejte', 'opatrně připájejte',\n"
            "  'podle instrukcí výrobce', 'pájecí tavidlo', 'výrobce pájecího',\n"
            "  'doporučené technologie', 'doporučených postupů', 'dle technologie',\n"
            "  'dle pokynů', 'pevně usazený', 'správně orientovaný a pevně',\n"
            "  'Poté je připájejte', 'Následně je připájejte'\n"
            "- Nezačínejte slovem 'Umístěte', 'Přidejte', 'Nyní' nebo 'V tomto kroku'\n"
            "- Pouze prostý text — bez uvozovek, odrážek, nadpisů, závorek navíc"
        )
    else:
        lang_instructions = (
            "Write ONE sentence describing this assembly step. This is a PCB soldering process.\n"
            "- English, natural language, addressing the reader directly\n"
            "- One direct sentence: what to solder and where — nothing more\n"
            "- The component type is given in parentheses after its designator — use EXACTLY that name; "
            "never write 'integrated circuit' or 'IC'\n"
            "- Component designators and values are already formatted in bold above — copy them as-is\n"
            "- Vary the verb: solder / install / fit / mount / tack down\n"
            "- Each step must sound distinct — vary verb and sentence structure\n"
            "- BANNED (must not appear anywhere in the output):\n"
            "  'glue', 'glued', 'stick', 'paste', 'carefully solder',\n"
            "  'per manufacturer instructions', 'according to', 'flux',\n"
            "  'Then solder', 'Then carefully'\n"
            "- Do not start with 'Place', 'Add', 'Now', or 'In this step'\n"
            "- Plain text only — no quotes, bullet points, headings"
        )

    return (
        "You are writing step-by-step assembly instructions for MkDocs documentation. "
        f"The module is called '{board_name}'.\n\n"
        "Each step shows a 3D render of the PCB at the current assembly state, "
        "with a short description displayed directly below the image. "
        "The description tells the reader exactly what to do. "
        "Use ONLY the information provided below — do not invent any details.\n\n"
        f"{step_context}\n\n"
        f"{lang_instructions}"
    )


# ---------------------------------------------------------------------------
# LLM backends
# ---------------------------------------------------------------------------

def _http_post(url: str, payload: dict, headers: dict | None = None, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={
                                 "Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:300]}") from e


def call_ollama(prompt: str, model: str, base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/api/chat"
    data = _http_post(url, {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    })
    return data["message"]["content"].strip()


def call_gemini(prompt: str, model: str, api_key: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )
    data = _http_post(url, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 200, "temperature": 0.7},
    })
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def call_deepl(text: str, api_key: str) -> str:
    # Free-tier keys end with :fx and use a different host
    host = "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"
    url = f"https://{host}/v2/translate"
    data = _http_post(
        url,
        {"text": [text], "source_lang": "EN", "target_lang": "CS"},
        headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
    )
    return data["translations"][0]["text"]


def call_anthropic(prompt: str, model: str, api_key: str) -> str:
    data = _http_post(
        "https://api.anthropic.com/v1/messages",
        {
            "model": model,
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        },
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    return data["content"][0]["text"].strip()


def call_argos(text: str) -> str:
    try:
        import argostranslate.package
        import argostranslate.translate
    except ImportError:
        raise RuntimeError(
            "argostranslate not installed — run: pip install argostranslate"
        )

    def _get_translation():
        langs = argostranslate.translate.get_installed_languages()
        en = next((l for l in langs if l.code == "en"), None)
        cs = next((l for l in langs if l.code == "cs"), None)
        if en and cs:
            return en.get_translation(cs)
        return None

    translation = _get_translation()
    if translation is None:
        print("  argos: downloading en→cs language pack…", file=sys.stderr)
        argostranslate.package.update_package_index()
        available = argostranslate.package.get_available_packages()
        pkg = next(
            (p for p in available if p.from_code == "en" and p.to_code == "cs"), None
        )
        if pkg is None:
            raise RuntimeError("en→cs package not found in argostranslate index")
        argostranslate.package.install_from_path(pkg.download())
        translation = _get_translation()
        if translation is None:
            raise RuntimeError("en→cs translation not available after install")

    return translation.translate(text)


# ---------------------------------------------------------------------------
# manual.md update
# ---------------------------------------------------------------------------

def _update_bom_in_text(text: str, bom_section: str, force: bool) -> str:
    """Insert or replace the BOM section (## Součástky / ## Components) in the document."""
    bom_heading = bom_section.split("\n")[0]  # e.g. "## Součástky"
    pos = text.find(bom_heading)
    if pos >= 0:
        if not force:
            return text
        # The BOM section is: heading + \n\n + table rows + \n\n + next content.
        # Skip the first \n\n (between heading and table) and find the second one
        # (between the last table row and the next content).
        after_heading = pos + len(bom_heading)
        first_blank = text.find("\n\n", after_heading)
        if first_blank < 0:
            return text[:pos] + bom_section
        second_blank = text.find("\n\n", first_blank + 2)
        end = second_blank if second_blank >= 0 else len(text)
        return text[:pos] + bom_section + text[end:]

    # No existing BOM — insert after the first # heading
    h1 = re.search(r"^# .+$", text, re.MULTILINE)
    if h1:
        return text[:h1.end()] + "\n\n" + bom_section + text[h1.end():]
    return bom_section + "\n\n" + text


def _is_step_content(para: str) -> bool:
    """True for paragraphs generated by this script: step headers, admonitions, descriptions."""
    return (
        bool(re.match(r"^### \d+", para)) or
        para.startswith("!!!") or
        (not para.startswith("#") and not para.startswith("|") and not IMG_RE.search(para))
    )


def update_manual(
    manual_path: pathlib.Path,
    step_descriptions: dict[str, str],
    force: bool,
    bom_section: str = "",
) -> None:
    """Insert BOM and step content (header + description) before each step image."""
    text = manual_path.read_text(encoding="utf-8")

    if bom_section:
        text = _update_bom_in_text(text, bom_section, force)

    paragraphs = re.split(r"\n{2,}", text.strip())

    result: list[str] = []
    i = 0
    while i < len(paragraphs):
        para = paragraphs[i]
        m = IMG_RE.search(para)
        if m:
            filename = m.group(1)
            content = step_descriptions.get(filename)
            if content:
                has_before = bool(result) and _is_step_content(result[-1])
                next_para = paragraphs[i + 1] if i + 1 < len(paragraphs) else ""
                has_after = bool(next_para) and not IMG_RE.search(next_para) and not next_para.startswith("#")

                if force:
                    # Remove any step content immediately preceding this image (previous run)
                    while result and _is_step_content(result[-1]):
                        result.pop()
                    result.append(content)
                    result.append(para)
                    # Clean up stale content that follows (old after-image format)
                    while i + 1 < len(paragraphs):
                        cand = paragraphs[i + 1]
                        if IMG_RE.search(cand) or cand.startswith("#"):
                            break
                        i += 1
                elif has_before or has_after:
                    result.append(para)  # content already exists — leave untouched
                else:
                    result.append(content)
                    result.append(para)
            else:
                result.append(para)
        else:
            result.append(para)
        i += 1

    manual_path.write_text("\n\n".join(result) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-board processing
# ---------------------------------------------------------------------------

def process_board(
    board_dir: pathlib.Path,
    generate_fn,
    dry_run: bool,
    print_only: bool,
    force: bool,
    translate_fn=None,
    target_lang: str = "en",
) -> bool:
    steps_path = board_dir / "render.steps"
    manual_path = board_dir / "manual.md"

    if not steps_path.exists():
        print(f"  skipping — no render.steps", file=sys.stderr)
        return False
    if not (manual_path.exists() or dry_run or print_only):
        print(f"  skipping — no manual.md", file=sys.stderr)
        return False

    component_values = extract_component_values(board_dir)
    _, steps = parse_steps(steps_path)

    # Build ref → section name map from render.steps (used as a type hint for LLM label generation).
    ref_sections: dict[str, str] = {}
    for _, section, new_refs, _ in steps:
        for ref in new_refs:
            ref_sections.setdefault(ref, section)

    # Build connector-subtype overrides from footprint data (JST SH, pin header, etc.).
    # Only override refs whose static type is the generic "konektor"/"connector" — don't
    # clobber more specific static types like "PMOD konektor" or custom J-prefix names.
    component_footprints = extract_component_footprints(board_dir)
    _generic_connector = "konektor" if target_lang == "cs" else "connector"
    connector_overrides: dict[str, str] = {}
    for ref, fp in component_footprints.items():
        static_type = _component_type_cs(ref) if target_lang == "cs" else _component_type(ref)
        if static_type == _generic_connector:
            label = _connector_type_from_footprint(fp, target_lang)
            if label:
                connector_overrides[ref] = label

    # Generate descriptive type labels for refs with no known Czech/English type (e.g. U-prefix).
    unknown_type_refs = {
        ref: val
        for ref, val in component_values.items()
        if not (_component_type_cs(ref) if target_lang == "cs" else _component_type(ref))
        and "_" not in val
        and re.search(r"\d", val)
    }
    extra_type_labels: dict[str, str] = {}
    # First: fill from the static translation table (reliable, no LLM needed).
    for ref in list(unknown_type_refs):
        section = ref_sections.get(ref, "")
        if section:
            key = re.sub(r"[-_\s]+", "-", section.lower()).strip("-")
            label = _SECTION_HINT_CS.get(key) or _SECTION_HINT_CS.get(section.lower())
            if label:
                extra_type_labels[ref] = label

    # Then: call LLM only for refs still without a label.
    remaining = {ref: val for ref, val in unknown_type_refs.items()
                 if ref not in extra_type_labels}
    if remaining and not dry_run:
        print(f"  generating type labels for: {', '.join(sorted(remaining))}")
        llm_labels = generate_unknown_type_labels(
            remaining, generate_fn, target_lang, ref_sections
        )
        extra_type_labels.update(llm_labels)

    # Merge connector overrides in last so they always win over LLM guesses.
    extra_type_labels.update(connector_overrides)

    if extra_type_labels:
        for ref, label in sorted(extra_type_labels.items()):
            print(f"  type label: {ref} → {label}")

    all_assembly_refs: set[str] = set()
    step_descriptions: dict[str, str] = {}
    ok = True
    for idx, section, new_refs, side in steps:
        all_assembly_refs.update(new_refs)
        filename = f"{idx:02d}-{_step_slug(section)}.png"
        refs_label = ", ".join(sorted(new_refs)) if new_refs else "empty board"
        print(f"  [{idx:02d}] {section} ({refs_label})")

        if dry_run:
            prompt = build_prompt(board_dir.name, section,
                                  new_refs, component_values, side, target_lang,
                                  extra_type_labels)
            print(f"       prompt preview: {prompt[:100].replace(chr(10), ' ')}…")
            continue

        header = f"### {idx}. {_step_header_label(new_refs, target_lang, extra_type_labels)}"

        if not new_refs:
            desc = "Prázdná deska připravená k osazování." if target_lang == "cs" \
                else "Start with the bare unpopulated board."
            print(f"       → {desc}  (fixed)")
            step_descriptions[filename] = f"{header}\n\n{desc}"
            continue

        prompt = build_prompt(board_dir.name, section,
                              new_refs, component_values, side, target_lang)
        try:
            desc = generate_fn(prompt)
            if translate_fn:
                en_desc = desc
                desc = translate_fn(desc)
                print(f"       en → {en_desc}")
                print(f"       cs → {desc}")
            else:
                print(f"       → {desc}")

            if target_lang == "cs":
                admonitions = [
                    adm for ref in sorted(new_refs)
                    if (adm := _polarization_admonition(ref, component_values))
                ]
                if admonitions:
                    desc = "\n\n".join(admonitions) + "\n\n" + desc

            step_descriptions[filename] = f"{header}\n\n{desc}"
        except Exception as e:
            print(f"       ! error: {e}", file=sys.stderr)
            ok = False

    if not dry_run and not print_only and step_descriptions:
        bom = generate_bom_section(
            all_assembly_refs, component_values, target_lang, extra_type_labels
        ) if all_assembly_refs else ""
        update_manual(manual_path, step_descriptions, force, bom_section=bom)
        print(f"  wrote {manual_path}")

    return ok


# ---------------------------------------------------------------------------
# README introduction generation
# ---------------------------------------------------------------------------

def build_readme_prompt(
    board_name: str,
    all_refs: set[str],
    component_values: dict[str, str],
    target_lang: str = "cs",
) -> str:
    """Build an LLM prompt that asks for a `# Title\n\nDescription` README intro."""
    groups: dict[tuple[str, str], list[str]] = {}
    for ref in sorted(all_refs):
        type_hint = (
            _component_type_cs(ref) if target_lang == "cs" else _component_type(ref)
        ) or "—"
        raw_val = component_values.get(ref, "")
        val = _normalize_value(raw_val, ref) \
            if raw_val and "_" not in raw_val and re.search(r"\d", raw_val) else "—"
        groups.setdefault((type_hint, val), []).append(ref)

    def _ref_sort_key(r: str) -> tuple[str, int]:
        m = re.match(r"([A-Za-z]+)(\d*)", r)
        return (m.group(1), int(m.group(2)) if m and m.group(2) else 0) if m else (r, 0)

    comp_lines = []
    for (type_hint, val), refs in sorted(groups.items()):
        label = _compact_refs(sorted(refs, key=_ref_sort_key))
        comp_lines.append(f"  {label}: {type_hint} ({val})")
    comp_block = "\n".join(comp_lines) if comp_lines else "  (žádné součástky)"

    board_hint = board_name.replace("_", " ").replace("-", " ")

    if target_lang == "cs":
        return (
            f"Jsi autor dokumentace pro open-source elektroniku. Piš pouze v češtině.\n\n"
            f"Vytvoř stručný úvod pro PMOD modul s interním názvem \"{board_hint}\".\n\n"
            f"Součástky na desce:\n{comp_block}\n\n"
            f"Výstup musí mít PŘESNĚ tento formát — nic jiného:\n"
            f"# Název modulu\n\n"
            f"Popis modulu.\n\n"
            f"Pravidla:\n"
            f"- Název (H1): 2–5 slov, výstižný český název co modul dělá\n"
            f"- Popis: 1–2 věty, co modul dělá a k čemu slouží\n"
            f"- Žádné obrázky, kódy, tabulky, nadpisy jiného stupně, odrážky\n"
            f"- Žádné uvozovky ani backticky kolem nadpisu\n"
            f"- Piš přirozenou hovorovou češtinou, stručně a věcně"
        )
    else:
        return (
            f"You are a technical writer for open-source electronics.\n\n"
            f"Write a brief introduction for a PMOD module called \"{board_hint}\".\n\n"
            f"Components on the board:\n{comp_block}\n\n"
            f"Output must have EXACTLY this format — nothing else:\n"
            f"# Module Name\n\n"
            f"Module description.\n\n"
            f"Rules:\n"
            f"- Heading (H1): 2–5 words, a clear descriptive name of what the module does\n"
            f"- Description: 1–2 sentences explaining what it does and what it is for\n"
            f"- No images, code blocks, tables, sub-headings, or bullet points\n"
            f"- No quotes or backticks around the heading\n"
            f"- Keep it concise and factual"
        )


def _update_readme_intro(text: str, new_intro: str, force: bool) -> str | None:
    """Replace the intro section (everything before the 3D render image) with new_intro.

    Returns None if the README already has real content and force is False.
    """
    paragraphs = re.split(r"\n{2,}", text.strip())

    image_idx: int | None = None
    for i, para in enumerate(paragraphs):
        if para.startswith("!["):
            image_idx = i
            break

    if image_idx is None:
        return new_intro.strip() + "\n\n" + text

    if not force:
        existing_desc_paras = [p for p in paragraphs[:image_idx] if not p.startswith("#")]
        has_real_content = any(
            p and "Co to je?" not in p
            for p in existing_desc_paras
        )
        if has_real_content:
            return None  # signal: already has content, skip

    intro_paras = new_intro.strip().split("\n\n")
    return "\n\n".join(intro_paras + paragraphs[image_idx:]) + "\n"


def process_readme(
    board_dir: pathlib.Path,
    generate_fn,
    dry_run: bool,
    print_only: bool,
    force: bool,
    target_lang: str = "cs",
) -> bool:
    """Generate and write the intro section (`# Title\n\nDescription`) of README.md."""
    readme_path = board_dir / "README.md"

    component_values = extract_component_values(board_dir)

    all_refs: set[str] = set()
    steps_path = board_dir / "render.steps"
    if steps_path.exists():
        _, steps = parse_steps(steps_path)
        for _, _, new_refs, _ in steps:
            all_refs.update(new_refs)
    if not all_refs:
        all_refs = set(component_values.keys())

    prompt = build_readme_prompt(board_dir.name, all_refs, component_values, target_lang)

    if dry_run:
        print(f"  prompt preview: {prompt[:120].replace(chr(10), ' ')}…")
        return True

    try:
        intro = generate_fn(prompt).strip()
    except Exception as e:
        print(f"  ! error: {e}", file=sys.stderr)
        return False

    if print_only:
        print(intro)
        return True

    print(f"  → {intro[:80].replace(chr(10), ' ')}…")

    if not readme_path.exists():
        image_block = (
            "![3D PCB](assets/default.png)\n\n"
            "| ![PCB top](assets/top.png) | ![PCB bottom](assets/bottom.png) |\n"
            "| --- | |\n\n"
            "![Schema](assets/schema.png)"
        )
        readme_path.write_text(intro + "\n\n" + image_block + "\n", encoding="utf-8")
        print(f"  created {readme_path}")
        return True

    text = readme_path.read_text(encoding="utf-8")
    new_text = _update_readme_intro(text, intro, force)
    if new_text is None:
        print(f"  skipped — README already has intro (use --force to overwrite)")
        return True
    readme_path.write_text(new_text, encoding="utf-8")
    print(f"  wrote {readme_path}")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "boards", nargs="*",
        help="Board directories to process (e.g. pmod/DPad pmod/joystick)",
    )
    parser.add_argument(
        "--board",
        help="Process a single board by name or path (e.g. --board DPad or --board pmod/DPad)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help=f"Process every board under {BOARD_ROOT}/",
    )
    parser.add_argument(
        "--provider", choices=["ollama", "gemini", "anthropic"], default="ollama",
        help="LLM provider (default: ollama)",
    )
    parser.add_argument(
        "--model",
        help="Model name. Ollama default: llama3.2  Gemini default: gemini-2.0-flash  "
             "Anthropic default: claude-haiku-4-5",
    )
    parser.add_argument(
        "--api-key",
        help="Gemini API key (or set GEMINI_API_KEY env var). Free tier: 1 500 req/day.",
    )
    parser.add_argument(
        "--anthropic-key",
        help="Anthropic API key (or set ANTHROPIC_API_KEY env var). "
             "Generates Czech directly — no translation step needed.",
    )
    parser.add_argument(
        "--ollama-url", default="http://localhost:11434",
        help="Ollama base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be generated without calling the LLM or writing files",
    )
    parser.add_argument(
        "--print-only", action="store_true",
        help="Call the LLM and print descriptions, but do not update manual.md",
    )
    parser.add_argument(
        "--deepl-key",
        help="DeepL API key to translate generated English text to Czech (or set DEEPL_API_KEY env var). "
             "Free tier: 500 000 chars/month. Free keys end with :fx.",
    )
    parser.add_argument(
        "--local-translate", action="store_true",
        help="Translate English output to Czech offline using argostranslate "
             "(pip install argostranslate). Downloads the en→cs language pack (~100 MB) on first use.",
    )
    parser.add_argument(
        "--lang", choices=["en", "cs"], default=None,
        help="Output language. Default: cs for anthropic provider, en for all others. "
             "Use --lang cs with a Czech-capable Ollama model to skip translation entirely.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite descriptions that already exist in manual.md / README.md",
    )
    parser.add_argument(
        "--readme", action="store_true",
        help="Also generate the intro section (title + description) for each board's README.md "
             "in addition to the assembly manual steps",
    )
    args = parser.parse_args(argv)

    if not args.boards and not args.board and not args.all:
        parser.print_help()
        return 1

    if args.all:
        board_dirs = sorted(
            d for d in BOARD_ROOT.iterdir() if d.is_dir() and d.name not in BLACKLIST
        )
    elif args.board:
        p = pathlib.Path(args.board)
        board_dirs = [p if p.parts[0] == BOARD_ROOT.name else BOARD_ROOT / p]
    else:
        board_dirs = [pathlib.Path(b) for b in args.boards]

    if args.provider == "gemini":
        api_key = args.api_key or os.environ.get("GEMINI_API_KEY", "")
        if not api_key and not args.dry_run:
            print(
                "Error: Gemini API key required — pass --api-key or set GEMINI_API_KEY.", file=sys.stderr)
            return 1
        model = args.model or "gemini-2.0-flash"
        def generate_fn(prompt): return call_gemini(prompt, model, api_key)
    elif args.provider == "anthropic":
        api_key = args.anthropic_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key and not args.dry_run:
            print(
                "Error: Anthropic API key required — pass --anthropic-key or set ANTHROPIC_API_KEY.",
                file=sys.stderr)
            return 1
        model = args.model or "claude-haiku-4-5"
        def generate_fn(prompt): return call_anthropic(prompt, model, api_key)
    else:
        model = args.model or "llama3.2"
        ollama_url = args.ollama_url
        def generate_fn(prompt): return call_ollama(prompt, model, ollama_url)

    default_lang = "cs" if args.provider == "anthropic" else "en"
    target_lang = args.lang or default_lang

    deepl_key = args.deepl_key or os.environ.get("DEEPL_API_KEY", "")
    if args.local_translate:
        translate_fn = call_argos
    elif deepl_key:
        translate_fn = lambda text: call_deepl(text, deepl_key)
    else:
        translate_fn = None

    all_ok = True
    for board_dir in board_dirs:
        print(f"\n{board_dir}")
        if args.readme:
            ok = process_readme(
                board_dir, generate_fn, args.dry_run, args.print_only, args.force,
                target_lang=target_lang,
            )
            all_ok = all_ok and ok
        ok = process_board(
            board_dir, generate_fn, args.dry_run, args.print_only, args.force,
            translate_fn=translate_fn, target_lang=target_lang,
        )
        all_ok = all_ok and ok

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
