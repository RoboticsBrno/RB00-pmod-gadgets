#!/usr/bin/env bash

set -euo pipefail

BOARD_PATH="${1:-}"
MODE="${2:-full}"

if [[ -z "$BOARD_PATH" ]]; then
  echo "Usage: $0 <board-dir|board.kicad_pcb> [full|dev]" >&2
  exit 1
fi

if [[ -d "$BOARD_PATH" ]]; then
  BOARD_DIR="$BOARD_PATH"
  shopt -s nullglob
  pcb_candidates=("$BOARD_DIR"/KiCad/*.kicad_pcb)
  shopt -u nullglob
  PCB_FILE="${pcb_candidates[0]:-}"
else
  PCB_FILE="$BOARD_PATH"
  BOARD_DIR="$(dirname "$(dirname "$PCB_FILE")")"
fi

if [[ ! -f "$PCB_FILE" ]]; then
  echo "Board file not found: $PCB_FILE" >&2
  exit 1
fi

if [[ ! -x ./render_board_assets.sh ]]; then
  echo "render_board_assets.sh is required" >&2
  exit 1
fi

OUT_DIR="${OUT_DIR:-$BOARD_DIR/.render-tmp}"

case "$MODE" in
  full)
    WIDTH="${WIDTH:-1000}"
    HEIGHT="${HEIGHT:-1000}"
    SUPERSAMPLE="${SUPERSAMPLE:-2}"
    STEP_RENDER_QUALITY="${STEP_RENDER_QUALITY:-high}"
    ;;
  dev)
    WIDTH="${WIDTH:-200}"
    HEIGHT="${HEIGHT:-200}"
    SUPERSAMPLE="${SUPERSAMPLE:-1}"
    STEP_RENDER_QUALITY="${STEP_RENDER_QUALITY:-basic}"
    ;;
  *)
    echo "Unknown mode: $MODE (use full or dev)" >&2
    exit 1
    ;;
esac

WIDTH="$WIDTH" HEIGHT="$HEIGHT" SUPERSAMPLE="$SUPERSAMPLE" STEP_RENDER_QUALITY="$STEP_RENDER_QUALITY" \
  ./render_board_assets.sh "$PCB_FILE" "$OUT_DIR"

echo "Rendered board: $PCB_FILE"
echo "Output: $OUT_DIR"
