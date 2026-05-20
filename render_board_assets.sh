#!/usr/bin/env bash

set -euo pipefail

BOARD_FILE="${1:-board.kicad_pcb}"
OUT_DIR="${2:-renders}"
RESOLUTION="${RESOLUTION:-1000}"
WIDTH="${WIDTH:-${RESOLUTION:-1000}}"
HEIGHT="${HEIGHT:-${RESOLUTION:-1000}}"
SUPERSAMPLE="${SUPERSAMPLE:-2}"
ROTATE="${ROTATE:--50,0,-45}"
ZOOM="${ZOOM:-0.75}"
SILK_OPACITY="${SILK_OPACITY:-0.9}"
SILK_SUPERSAMPLE="${SILK_SUPERSAMPLE:-1}"
BOARD_BASENAME="${BOARD_FILE##*/}"
BOARD_BASENAME="${BOARD_BASENAME%.*}"
BOARD_DIR="$(dirname "$(dirname "$BOARD_FILE")")"
ZOOM_FILE="$BOARD_DIR/render.zoom"
STEP_CONFIG_FILE="${STEP_CONFIG_FILE:-$BOARD_DIR/render.steps}"
STEP_OUT_DIR="${STEP_OUT_DIR:-$OUT_DIR/steps}"
STEP_RENDERER="${STEP_RENDERER:-./render_board_steps.py}"
TMP_DIR="${TMP_DIR:-$OUT_DIR/tmp}"
USED_FILES=()

STEP_CLIP="${STEP_CLIP:-0}"
STEP_HIGHLIGHT="${STEP_HIGHLIGHT:-0}"

if [[ ! -f "$BOARD_FILE" ]]; then
  echo "Board file not found: $BOARD_FILE" >&2
  exit 1
fi

if ! command -v kicad-cli >/dev/null 2>&1; then
  echo "kicad-cli is required" >&2
  exit 1
fi

if command -v magick >/dev/null 2>&1; then
  IMG_CONVERT=(magick)
elif command -v convert >/dev/null 2>&1; then
  IMG_CONVERT=(convert)
else
  echo "ImageMagick (magick or convert) is required" >&2
  exit 1
fi

if [[ -f "$ZOOM_FILE" ]]; then
  read -r FIRST_LINE < "$ZOOM_FILE" || true
  if [[ "$FIRST_LINE" =~ ^[[:space:]]*\[ ]]; then
    STEP_CONFIG_FILE="$ZOOM_FILE"
  elif [[ -n "$FIRST_LINE" ]]; then
    ZOOM="$(tr -d '[:space:]' < "$ZOOM_FILE")"
  fi
fi

mkdir -p "$OUT_DIR" "$TMP_DIR"

track_file() {
  USED_FILES+=("$1")
}

render_3d() {
  local side="$1"
  local output="$2"
  local temp_png="$TMP_DIR/${side}.png"

  kicad-cli pcb render \
    --output "$temp_png" \
    --width "$WIDTH" \
    --height "$HEIGHT" \
    --side "$side" \
    --rotate "$ROTATE" \
    --zoom "$ZOOM" \
    --perspective \
    --background transparent \
    --quality high \
    "$BOARD_FILE"

  track_file "$temp_png"
  [[ -f "$ZOOM_FILE" ]] && track_file "$ZOOM_FILE"

  cp "$temp_png" "$output"

  track_file "$output"
}

render_layer() {
  local layer="$1"
  local output="$2"
  local mirror_flag="${3:-}"
  local supersample_factor="${4:-$SUPERSAMPLE}"
  local svg_file="$TMP_DIR/${layer//./_}.svg"
  local supersampled_png="$TMP_DIR/${layer//./_}-${supersample_factor}x.png"
  local longest_side=$((WIDTH > HEIGHT ? WIDTH : HEIGHT))
  local raster_size=$((longest_side * supersample_factor))

  kicad-cli pcb export svg \
    --mode-single \
    --output "$svg_file" \
    --layers "$layer" \
    --page-size-mode 2 \
    --fit-page-to-board \
    --exclude-drawing-sheet \
    ${mirror_flag:+--mirror} \
    "$BOARD_FILE"

  rsvg-convert \
    --format png \
    --background-color transparent \
    --width "$raster_size" \
    --keep-aspect-ratio \
    --output "$supersampled_png" \
    "$svg_file"

  track_file "$svg_file"
  track_file "$supersampled_png"

  "${IMG_CONVERT[@]}" "$supersampled_png" \
    -background none \
    -filter Lanczos \
    -resize "${WIDTH}x${HEIGHT}" \
    -gravity center \
    -extent "${WIDTH}x${HEIGHT}" \
    "$output"

  track_file "$output"
}

render_hole_mask() {
  local output="$1"
  local source_svg="$2"
  local holes_svg="$TMP_DIR/holes.svg"
  local holes_png="$TMP_DIR/holes.png"
  local raster_size=$(( (WIDTH > HEIGHT ? WIDTH : HEIGHT) * SUPERSAMPLE ))
  python - "$source_svg" "$holes_svg" <<'PY'
import sys
from copy import deepcopy
import xml.etree.ElementTree as ET

source_svg, out_svg_path = sys.argv[1:3]
tree = ET.parse(source_svg)
root = tree.getroot()
ET.register_namespace('', 'http://www.w3.org/2000/svg')
svg = ET.Element(root.tag, root.attrib)

def is_black_style(attrs):
    style = attrs.get('style', '').lower()
    fill = attrs.get('fill', '').lower()
    return (
        'fill:#ffffff' in style or
        'fill:white' in style or
        fill in {'#ffffff', 'white'}
    )

def walk(node, black=False):
    node_black = black or is_black_style(node.attrib)
    tag = node.tag.rsplit('}', 1)[-1]
    if tag == 'circle' and node_black:
        circle = deepcopy(node)
        circle.attrib.pop('style', None)
        circle.attrib['fill'] = '#000000'
        circle.attrib['fill-opacity'] = '1'
        circle.attrib['stroke'] = 'none'
        svg.append(circle)
    for child in list(node):
        walk(child, node_black)

walk(root)

ET.ElementTree(svg).write(out_svg_path, encoding='utf-8', xml_declaration=True)
PY

  track_file "$holes_svg"

  rsvg-convert \
    --format png \
    --background-color transparent \
    --width "$raster_size" \
    --keep-aspect-ratio \
    --output "$holes_png" \
    "$holes_svg"

  track_file "$holes_png"

  "${IMG_CONVERT[@]}" "$holes_png" \
    -background none \
    -filter Lanczos \
    -resize "${WIDTH}x${HEIGHT}" \
    -gravity center \
    -extent "${WIDTH}x${HEIGHT}" \
    "$output"

  track_file "$output"
}

render_layer_with_silk() {
  local copper_layer="$1"
  local silk_layer="$2"
  local output="$3"
  local mirror_flag="${4:-}"
  local copper_png="$TMP_DIR/${copper_layer//./_}.png"
  local silk_png="$TMP_DIR/${silk_layer//./_}.png"
  local combined_png="$TMP_DIR/${copper_layer//./_}+${silk_layer//./_}.png"

  render_layer "$copper_layer" "$copper_png" "$mirror_flag" "$SUPERSAMPLE"
  render_layer "$silk_layer" "$silk_png" "$mirror_flag" "$SILK_SUPERSAMPLE"

  "${IMG_CONVERT[@]}" "$silk_png" \
    -alpha set \
    -channel A \
    -evaluate multiply "$SILK_OPACITY" \
    +channel \
    "$silk_png"

  "${IMG_CONVERT[@]}" "$copper_png" "$silk_png" \
    -background none \
    -compose over \
    -composite \
    "$combined_png"

  local holes_png="$TMP_DIR/holes-mask.png"
  local copper_svg="$TMP_DIR/${copper_layer//./_}.svg"

  render_hole_mask "$holes_png" "$copper_svg"

  "${IMG_CONVERT[@]}" "$combined_png" "$holes_png" \
    -compose dstout \
    -composite \
    "$combined_png"

  cp "$combined_png" "$output"

  track_file "$copper_png"
  track_file "$silk_png"
  track_file "$combined_png"
  track_file "$holes_png"
  track_file "$output"
}

render_3d top "$OUT_DIR/3d-top.png"
render_layer_with_silk F.Cu F.SilkS "$OUT_DIR/top-copper.png"
render_layer_with_silk B.Cu B.SilkS "$OUT_DIR/bottom-copper.png" mirror

if [[ -f "$STEP_CONFIG_FILE" ]]; then
  if [[ ! -f "$STEP_RENDERER" ]]; then
    echo "Step renderer not found: $STEP_RENDERER" >&2
    exit 1
  fi

  EXTRA_ARGS=()
  [[ "$STEP_CLIP" =~ ^(1|true|yes|on)$ ]] && EXTRA_ARGS+=("--clip")
  [[ "$STEP_HIGHLIGHT" =~ ^(1|true|yes|on)$ ]] && EXTRA_ARGS+=("--highlight")

  mkdir -p "$STEP_OUT_DIR"
  python3 "$STEP_RENDERER" \
    "$BOARD_FILE" \
    "$STEP_OUT_DIR" \
    --config "$STEP_CONFIG_FILE" \
    --width "$WIDTH" \
    --height "$HEIGHT" \
    --rotate="$ROTATE" \
    --zoom "$ZOOM" \
    --quality "${STEP_RENDER_QUALITY:-high}" \
    --background transparent \
    "${EXTRA_ARGS[@]}"
fi

echo "Rendered assets in: $OUT_DIR"
echo "Used files:"
printf '%s\n' "${USED_FILES[@]}"
