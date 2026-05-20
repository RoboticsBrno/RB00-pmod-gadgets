#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="${1:-pmod}"

if ! command -v ./render_board_assets.sh >/dev/null 2>&1; then
  echo "render_board_assets.sh is required" >&2
  exit 1
fi

for pcb in "$ROOT_DIR"/*/KiCad/*.kicad_pcb; do
  [[ -f "$pcb" ]] || continue
  board_dir="$(dirname "$(dirname "$pcb")")"
  assets_dir="$board_dir/assets"
  tmp_out="$board_dir/.render-tmp"

  mkdir -p "$assets_dir"

  WIDTH=400 \
  HEIGHT=400 \
  SUPERSAMPLE=1 \
  STEP_RENDER_QUALITY=basic \
  STEP_CLIP=1 \
  STEP_HIGHLIGHT=1 \
  ./render_board_assets.sh "$pcb" "$tmp_out"
  cp "$tmp_out/top-copper.png" "$assets_dir/top.png"
  cp "$tmp_out/bottom-copper.png" "$assets_dir/bottom.png"
  cp "$tmp_out/3d-top.png" "$assets_dir/default.png"
  cp -r "$tmp_out/steps" "$assets_dir/"
done
