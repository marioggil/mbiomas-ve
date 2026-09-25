#!/usr/bin/env bash
# Single entrypoint for the MapBiomas Venezuela viewer feature.
#
# This script exists so a clean clone of the repository becomes a running
# viewer with a single command, and so the data pipeline is reproducible
# from the same entrypoint without people reaching into tools/ by hand.
#
# The repository carries code and small derived metadata only. The 13 GB of
# geospatial data lives under data/raw, data/cog and data/tiles and is
# gitignored. A fresh clone therefore starts without data; see ./run.sh
# check for the honest state and ./run.sh pipeline for the rebuild route.
#
# Usage:
#   ./run.sh check                 # verify prerequisites for serving
#   ./run.sh pipeline [--force] [--dry-run]   # rebuild data from raw rasters
#   ./run.sh serve [port]          # start the viewer (default port 8000)
#
# Environment variables:
#   MAPBIOMAS_COUNTRY      country id (default: venezuela)
#   MAPBIOMAS_COLLECTION   collection id (default: 3)
#   MAPBIOMAS_REPO_ROOT    repository root; honoured by the service so a
#                          data tree that lives outside the checkout is used
#                          as if it were inside it. Defaults to this script's
#                          parent directory.
#   PORT                   uvicorn bind port, used by `serve` when no
#                          positional port is given (default: 8000).

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths and configuration
# ---------------------------------------------------------------------------

# Resolve the repo root from the script's own location so the script works
# from any working directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${MAPBIOMAS_REPO_ROOT:-$SCRIPT_DIR}"
export MAPBIOMAS_REPO_ROOT="$REPO_ROOT"

COUNTRY="${MAPBIOMAS_COUNTRY:-venezuela}"
COLLECTION="${MAPBIOMAS_COLLECTION:-3}"

DATA_DIR="$REPO_ROOT/data"
LEGEND_DIR="$DATA_DIR/legend"
RAW_DIR="$DATA_DIR/raw/$COUNTRY/collection-$COLLECTION"
COG_DIR="$DATA_DIR/cog/$COUNTRY/collection-$COLLECTION"
DERIVED_DIR="$DATA_DIR/derived/$COUNTRY/collection-$COLLECTION"
TILES_DIR="$DATA_DIR/tiles/$COUNTRY/collection-$COLLECTION"
COMPOSITION_DIR="$DERIVED_DIR/composition"

CODEBOOK_JSON="$LEGEND_DIR/${COUNTRY}-collection-${COLLECTION}.json"
CODEBOOK_CSV="$LEGEND_DIR/${COUNTRY}-collection-${COLLECTION}.csv"
CODEBOOK_PDF="$LEGEND_DIR/source/MB-${COUNTRY^}-Col-${COLLECTION}-Legend-Code.pdf"
# The country name in the PDF/QGIS filenames is capitalised; the bash ${COUNTRY^}
# substitution gives "Venezuela" for "venezuela", which is what the source
# filenames use. Override here if the convention changes.
CODEBOOK_PDF="$LEGEND_DIR/source/MB-Venezuela-Col-${COLLECTION}-Legend-Code.pdf"
CODEBOOK_QML="$LEGEND_DIR/source/QGIS_Leyenda_col${COLLECTION}.qml"

COG_MANIFEST="$DERIVED_DIR/cog-manifest.json"
TILES_MANIFEST="$DERIVED_DIR/tiles-manifest.json"
COMPOSITION_L1="$COMPOSITION_DIR/composition-level1-${COUNTRY}-collection-${COLLECTION}.csv"
COMPOSITION_L2="$COMPOSITION_DIR/composition-level2-${COUNTRY}-collection-${COLLECTION}.csv"
COMPOSITION_SUMMARY="$COMPOSITION_DIR/composition-summary-${COUNTRY}-collection-${COLLECTION}.json"

VIEWER_DIR="$REPO_ROOT/viewer"
REQUIREMENTS_FILE="$VIEWER_DIR/requirements.txt"
VENV_DIR="$REPO_ROOT/.venv"

TOOLS_DIR="$REPO_ROOT/tools"
PY_CODEBOOK="$TOOLS_DIR/build_codebook.py"
PY_COG="$TOOLS_DIR/normalize_to_cog.py"
PY_COMPOSITION="$TOOLS_DIR/composition_stats.py"
PY_TILES="$TOOLS_DIR/build_tiles.py"
PY_SERVE="$TOOLS_DIR/serve_viewer.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    printf '%s\n' "$*"
}

err() {
    printf 'error: %s\n' "$*" >&2
}

die() {
    err "$*"
    exit 2
}

# `which` is non-portable; command -v is POSIX and always available.
have_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# format_seconds 95 -> "1m 35s", 3700 -> "1h 1m 40s"
format_seconds() {
    local total=$1
    if [ "$total" -lt 60 ]; then
        printf '%ss' "$total"
        return
    fi
    if [ "$total" -lt 3600 ]; then
        printf '%sm %02ds' $((total / 60)) $((total % 60))
        return
    fi
    printf '%sh %02dm %02ds' $((total / 3600)) $(((total / 60) % 60)) $((total % 60))
}

# Print a numbered check item and record its serve/rebuild category.
# Usage: check_item "needed to serve" "<label>" "<path-expr>" <test>
# The fourth argument is evaluated by the caller with `eval`.
SERVING_OK=0
SERVING_MISSING=0
REBUILD_MISSING=0

record_serve_missing() {
    SERVING_MISSING=$((SERVING_MISSING + 1))
}

record_rebuild_missing() {
    REBUILD_MISSING=$((REBUILD_MISSING + 1))
}

# A POSIX-friendly stat that prints file size in bytes; used to decide whether
# a tiles directory is more than an empty skeleton.
dir_has_files() {
    [ -d "$1" ] && [ -n "$(ls -A "$1" 2>/dev/null)" ]
}

# count_files <dir> [find args...]
# Prints the number of matching files under <dir>, or 0 when the directory does not
# exist.
#
# A bare `$(find "$dir" ... | wc -l)` is a landmine in this script: with `set -e`
# and `pipefail`, find's non-zero exit on a missing directory fails the whole
# assignment and aborts the entire run. That broke `pipeline` exactly on a fresh
# clone, which is the case this packaging exists for.
count_files() {
    local dir="$1"; shift
    [ -d "$dir" ] || { printf '0'; return 0; }
    { find "$dir" "$@" 2>/dev/null || true; } | wc -l | tr -d ' '
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_check() {
    log "MapBiomas Venezuela — prerequisites check"
    log "Country: $COUNTRY / Collection: $COLLECTION"
    log "Repository root: $REPO_ROOT"
    log ""
    log "Items marked [serve] are needed for \`./run.sh serve\`."
    log "Items marked [rebuild] are needed only when you intend to run"
    log "\`./run.sh pipeline\` to regenerate the data from raw rasters."
    log ""

    SERVING_OK=0
    SERVING_MISSING=0
    REBUILD_MISSING=0

    # --- Tools required to (re)build the data and to serve ---
    if have_cmd python3; then
        log "  [serve] python3         $(command -v python3)   OK"
    else
        log "  [serve] python3         MISSING — install Python 3.13 or use the system package"
        record_serve_missing
    fi
    if have_cmd uv; then
        log "  [serve] uv              $(command -v uv)   OK"
    else
        log "  [serve] uv              MISSING — install with: pip install uv  (or: pipx install uv)"
        record_serve_missing
    fi
    if have_cmd git; then
        log "  [serve] git             $(command -v git)   OK"
    else
        log "  [serve] git             MISSING — install git (used only for the symlink hint)"
        record_serve_missing
    fi

    # --- Codebook: needed to serve AND to rebuild ---
    if [ -f "$CODEBOOK_JSON" ]; then
        log "  [serve] codebook JSON   $CODEBOOK_JSON   OK"
    else
        log "  [serve] codebook JSON   $CODEBOOK_JSON   MISSING"
        log "             rebuild:  ./run.sh pipeline    (or only stage 1: tools/build_codebook.py ...)"
        record_serve_missing
    fi

    # --- COG outputs: needed to serve (the tile pyramid is built from them
    #     and the viewer parses the BigTIFF header of every tile request)
    if [ -d "$COG_DIR" ] && dir_has_files "$COG_DIR"; then
        local n
        n=$(count_files "$COG_DIR" -maxdepth 1 -name '*.tif')
        log "  [serve] COG directory   $COG_DIR   OK ($n .tif files)"
    else
        log "  [serve] COG directory   $COG_DIR   MISSING (no .tif files)"
        log "             rebuild:  ./run.sh pipeline"
        record_serve_missing
    fi
    if [ -f "$COG_MANIFEST" ]; then
        log "  [serve] COG manifest    $COG_MANIFEST   OK"
    else
        log "  [serve] COG manifest    $COG_MANIFEST   MISSING"
        log "             rebuild:  ./run.sh pipeline    (regenerated together with the COGs)"
        record_serve_missing
    fi

    # --- Composition outputs: needed to serve (the composition panel reads them) ---
    if [ -f "$COMPOSITION_L1" ]; then
        log "  [serve] composition L1  $COMPOSITION_L1   OK"
    else
        log "  [serve] composition L1  $COMPOSITION_L1   MISSING"
        log "             rebuild:  ./run.sh pipeline"
        record_serve_missing
    fi
    if [ -f "$COMPOSITION_L2" ]; then
        log "  [serve] composition L2  $COMPOSITION_L2   OK"
    else
        log "  [serve] composition L2  $COMPOSITION_L2   MISSING"
        log "             rebuild:  ./run.sh pipeline"
        record_serve_missing
    fi
    if [ -f "$COMPOSITION_SUMMARY" ]; then
        log "  [serve] composition summary JSON   $COMPOSITION_SUMMARY   OK"
    else
        log "  [serve] composition summary JSON   $COMPOSITION_SUMMARY   MISSING"
        log "             rebuild:  ./run.sh pipeline"
        record_serve_missing
    fi

    # --- Tiles pyramid + manifest: needed to serve ---
    if [ -d "$TILES_DIR" ] && dir_has_files "$TILES_DIR"; then
        local n
        n=$(count_files "$TILES_DIR" -name '*.png')
        log "  [serve] tiles pyramid   $TILES_DIR   OK ($n .png files)"
    else
        log "  [serve] tiles pyramid   $TILES_DIR   MISSING"
        log "             rebuild:  ./run.sh pipeline"
        record_serve_missing
    fi
    if [ -f "$TILES_MANIFEST" ]; then
        log "  [serve] tiles manifest  $TILES_MANIFEST   OK"
    else
        log "  [serve] tiles manifest  $TILES_MANIFEST   MISSING"
        log "             rebuild:  ./run.sh pipeline    (regenerated together with the pyramid)"
        record_serve_missing
    fi

    # --- Python dependencies: needed to serve ---
    if [ -x "$VENV_DIR/bin/python" ]; then
        if "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, pydantic" >/dev/null 2>&1; then
            log "  [serve] viewer deps     $VENV_DIR   OK"
        else
            log "  [serve] viewer deps     $VENV_DIR   INCOMPLETE"
            log "             rebuild:  ./run.sh serve    (creates and installs the .venv)"
            record_serve_missing
        fi
    else
        log "  [serve] viewer deps     $VENV_DIR   MISSING"
        log "             rebuild:  ./run.sh serve    (creates and installs the .venv)"
        record_serve_missing
    fi

    # --- Raw rasters: needed only to rebuild from scratch ---
    if [ -d "$RAW_DIR" ] && dir_has_files "$RAW_DIR"; then
        local n
        n=$(count_files "$RAW_DIR" -maxdepth 1 -name '*.tif')
        log "  [rebuild] raw rasters   $RAW_DIR   OK ($n .tif files)"
    else
        log "  [rebuild] raw rasters   $RAW_DIR   MISSING (no .tif files)"
        log "             rebuild:  drop the 40 MapBiomas rasters into this directory and rerun check"
        log "             OR       point MAPBIOMAS_REPO_ROOT at a checkout that already has them and rerun check"
        log "             OR       symlink them in:  ln -s /path/to/raw/venezuela/collection-3 $RAW_DIR"
        record_rebuild_missing
    fi
    if [ -f "$CODEBOOK_PDF" ]; then
        log "  [rebuild] codebook PDF  $CODEBOOK_PDF   OK"
    else
        log "  [rebuild] codebook PDF  $CODEBOOK_PDF   MISSING (only needed to (re)build the codebook)"
        log "             rebuild:  drop MB-Venezuela-Col-3-Legend-Code.pdf under data/legend/source/"
        record_rebuild_missing
    fi
    if [ -f "$CODEBOOK_QML" ]; then
        log "  [rebuild] QGIS legend   $CODEBOOK_QML   OK"
    else
        log "  [rebuild] QGIS legend   $CODEBOOK_QML   MISSING (only needed as a codebook cross-check)"
        log "             rebuild:  drop QGIS_Leyenda_col3.qml under data/legend/source/"
        record_rebuild_missing
    fi

    log ""
    log "Hint: the data is not in the repository (it is gitignored, ~13 GB)."
    log "Two ways to bring it into a fresh clone:"
    log "  1. Rebuild it from the MapBiomas rasters with:  ./run.sh pipeline"
    log "     Measured cost: ~17-25 min (COG) + ~25 min (composition) + ~110 min (tiles) = ~2.5-3 h for 40 years."
    log "  2. Point this checkout at an existing data tree:"
    log "       export MAPBIOMAS_REPO_ROOT=/path/to/other/checkout"
    log "     The service already honours that variable; the same is true when you"
    log "     symlink the data directories from the other checkout:"
    log "       ln -s /path/to/other/checkout/data/raw data/raw"
    log "       ln -s /path/to/other/checkout/data/cog data/cog"
    log "       ln -s /path/to/other/checkout/data/tiles data/tiles"
    log "       ln -s /path/to/other/checkout/data/derived data/derived"
    log ""

    if [ "$SERVING_MISSING" -eq 0 ]; then
        log "OK: every prerequisite needed to serve is present."
        return 0
    fi
    log "FAIL: $SERVING_MISSING serving prerequisite(s) missing (plus $REBUILD_MISSING rebuild-only)."
    return 1
}

# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

stage_codebook() {
    # Codebook depends on the PDF + QML files only. It produces a JSON and a
    # CSV under data/legend; both are needed to serve. Skip when both exist.
    if [ -f "$CODEBOOK_JSON" ] && [ -f "$CODEBOOK_CSV" ] && [ "${FORCE:-0}" -eq 0 ]; then
        log "  codebook: outputs exist, skipping"
        return 0
    fi
    log "  codebook: measured cost ~seconds"
    log "  codebook: running tools/build_codebook.py"
    local cmd=(
        python3 "$PY_CODEBOOK"
        --country "$COUNTRY"
        --collection "$COLLECTION"
        --pdf "$CODEBOOK_PDF"
        --qml "$CODEBOOK_QML"
        --outdir "$LEGEND_DIR"
    )
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
        printf '  codebook would run:'
        printf ' %q' "${cmd[@]}"
        printf '\n'
        return 0
    fi
    "${cmd[@]}"
}

stage_cog() {
    # COG normalisation: needs raw rasters; produces 40 .tif files + manifest.
    if [ -f "$COG_MANIFEST" ] && [ "${FORCE:-0}" -eq 0 ]; then
        local existing
        existing=$(count_files "$COG_DIR" -maxdepth 1 -name '*.tif')
        if [ "$existing" -ge 40 ]; then
            log "  cog: manifest + $existing COG files exist, skipping"
            return 0
        fi
    fi
    if [ ! -d "$RAW_DIR" ] || [ -z "$(ls -A "$RAW_DIR" 2>/dev/null)" ]; then
        if [ "${DRY_RUN:-0}" -eq 1 ]; then
            log "  cog: NOTE raw rasters absent right now ($RAW_DIR); printing the command anyway"
        else
            err "  cog: raw rasters missing in $RAW_DIR — cannot normalise"
            return 1
        fi
    fi
    log "  cog: measured cost ~17-25 min for 40 years (~25 s/year)"
    log "  cog: running tools/normalize_to_cog.py"
    local cmd=(
        python3 "$PY_COG"
        --country "$COUNTRY"
        --collection "$COLLECTION"
        --input-dir "$RAW_DIR"
        --output-dir "$COG_DIR"
        --manifest "$COG_MANIFEST"
    )
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
        printf '  cog would run:'
        printf ' %q' "${cmd[@]}"
        printf '\n'
        return 0
    fi
    "${cmd[@]}"
}

stage_composition() {
    # Composition statistics: needs the COGs + the codebook; produces three files
    # under data/derived/<country>/collection-<n>/composition/.
    if [ -f "$COMPOSITION_L1" ] && [ -f "$COMPOSITION_L2" ] && [ -f "$COMPOSITION_SUMMARY" ] && [ "${FORCE:-0}" -eq 0 ]; then
        log "  composition: outputs exist, skipping"
        return 0
    fi
    if [ ! -f "$CODEBOOK_JSON" ]; then
        if [ "${DRY_RUN:-0}" -eq 1 ]; then
            log "  composition: NOTE codebook absent right now; printing the command anyway"
        else
            err "  composition: codebook missing at $CODEBOOK_JSON — run stage 1 first"
            return 1
        fi
    fi
    if [ ! -d "$COG_DIR" ] || [ -z "$(ls -A "$COG_DIR" 2>/dev/null)" ]; then
        if [ "${DRY_RUN:-0}" -eq 1 ]; then
            log "  composition: NOTE COGs absent right now; printing the command anyway"
        else
            err "  composition: COGs missing in $COG_DIR — run stage 2 first"
            return 1
        fi
    fi
    log "  composition: measured cost ~25 min for 40 years (~38 s/year)"
    log "  composition: running tools/composition_stats.py"
    local cmd=(
        python3 "$PY_COMPOSITION"
        --country "$COUNTRY"
        --collection "$COLLECTION"
        --cog-dir "$COG_DIR"
        --codebook "$CODEBOOK_JSON"
        --outdir "$COMPOSITION_DIR"
    )
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
        printf '  composition would run:'
        printf ' %q' "${cmd[@]}"
        printf '\n'
        return 0
    fi
    "${cmd[@]}"
}

stage_tiles() {
    # Tile pyramid: needs the COGs + the codebook; produces data/tiles/... + manifest.
    if [ -f "$TILES_MANIFEST" ] && [ "${FORCE:-0}" -eq 0 ]; then
        local existing
        existing=$(count_files "$TILES_DIR" -name '*.png')
        if [ "$existing" -ge 1000 ]; then
            log "  tiles: manifest + $existing tile files exist, skipping"
            return 0
        fi
    fi
    if [ ! -f "$CODEBOOK_JSON" ]; then
        if [ "${DRY_RUN:-0}" -eq 1 ]; then
            log "  tiles: NOTE codebook absent right now; printing the command anyway"
        else
            err "  tiles: codebook missing at $CODEBOOK_JSON — run stage 1 first"
            return 1
        fi
    fi
    if [ ! -d "$COG_DIR" ] || [ -z "$(ls -A "$COG_DIR" 2>/dev/null)" ]; then
        if [ "${DRY_RUN:-0}" -eq 1 ]; then
            log "  tiles: NOTE COGs absent right now; printing the command anyway"
        else
            err "  tiles: COGs missing in $COG_DIR — run stage 2 first"
            return 1
        fi
    fi
    log "  tiles: measured cost ~110 min for 40 years (~140-164 s/year)"
    log "  tiles: running tools/build_tiles.py"
    local cmd=(
        python3 "$PY_TILES"
        --country "$COUNTRY"
        --collection "$COLLECTION"
        --cog-dir "$COG_DIR"
        --codebook "$CODEBOOK_JSON"
        --outdir "$TILES_DIR"
        --manifest "$TILES_MANIFEST"
    )
    if [ "${DRY_RUN:-0}" -eq 1 ]; then
        printf '  tiles would run:'
        printf ' %q' "${cmd[@]}"
        printf '\n'
        return 0
    fi
    "${cmd[@]}"
}

cmd_pipeline() {
    FORCE=0
    DRY_RUN=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --force) FORCE=1 ;;
            --dry-run) DRY_RUN=1 ;;
            -h|--help)
                log "Usage: ./run.sh pipeline [--force] [--dry-run]"
                return 0
                ;;
            *)
                die "unknown pipeline flag: $1"
                ;;
        esac
        shift
    done

    log "MapBiomas Venezuela — data pipeline"
    log "Country: $COUNTRY / Collection: $COLLECTION"
    log "Repository root: $REPO_ROOT"
    if [ "$DRY_RUN" -eq 1 ]; then
        log "Mode: dry run (no commands will be executed)"
    elif [ "$FORCE" -eq 1 ]; then
        log "Mode: force (existing outputs will be overwritten)"
    else
        log "Mode: incremental (stages with existing outputs are skipped)"
    fi
    log ""

    local t0 t1
    t0=$(date +%s)
    stage_codebook
    stage_cog
    stage_composition
    stage_tiles
    t1=$(date +%s)
    log ""
    log "pipeline: done in $(format_seconds $((t1 - t0)))"
}

# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------

ensure_venv() {
    if [ -x "$VENV_DIR/bin/python" ]; then
        if "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, pydantic" >/dev/null 2>&1; then
            log "  .venv: already present and complete"
            return 0
        fi
        log "  .venv: present but dependencies are incomplete; recreating"
        rm -rf "$VENV_DIR"
    else
        log "  .venv: not present; creating with uv"
    fi
    if [ ! -f "$REQUIREMENTS_FILE" ]; then
        err "  requirements file missing: $REQUIREMENTS_FILE"
        return 1
    fi
    uv venv "$VENV_DIR" --python python3
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    uv pip install -r "$REQUIREMENTS_FILE"
}

cmd_serve() {
    local port="${PORT:-8000}"
    if [ $# -gt 0 ]; then
        port="$1"
    fi
    export PORT="$port"

    log "MapBiomas Venezuela — serve"
    log "Country: $COUNTRY / Collection: $COLLECTION"
    log "Repository root: $REPO_ROOT"
    log ""

    # Build the Python environment FIRST. On a fresh clone it does not exist yet,
    # and running the prerequisites check before creating it would fail on the very
    # thing this command is about to create, making the documented onboarding path
    # impossible. ensure_venv is idempotent, so an existing complete environment is
    # left alone.
    log "Setting up the Python environment..."
    ensure_venv

    # Then verify everything, including the environment just created, so a failure
    # message is honest about what is actually missing.
    if ! cmd_check >/dev/null; then
        err "prerequisites check failed; run './run.sh check' for details"
        return 1
    fi

    log ""
    log "Starting uvicorn on 0.0.0.0:$port (override with: PORT=9000 ./run.sh serve)"
    log "Viewer URL: http://localhost:$port/"
    log ""

    cd "$REPO_ROOT"
    exec "$VENV_DIR/bin/python" -m uvicorn \
        --app-dir "$TOOLS_DIR" \
        --host 0.0.0.0 \
        --port "$port" \
        serve_viewer:app
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

usage() {
    cat <<'EOF'
MapBiomas Venezuela — packaging entrypoint

Usage:
  ./run.sh check                  verify serving prerequisites
  ./run.sh pipeline [--force] [--dry-run]
                                  rebuild data from raw rasters
  ./run.sh serve [port]           start the viewer (default port 8000)

Environment:
  MAPBIOMAS_COUNTRY       country id (default: venezuela)
  MAPBIOMAS_COLLECTION    collection id (default: 3)
  MAPBIOMAS_REPO_ROOT     repo root used by the service
  PORT                    uvicorn bind port (default: 8000)

See README.md for the full onboarding walkthrough.
EOF
}

main() {
    if [ $# -lt 1 ]; then
        usage
        exit 1
    fi
    local sub="$1"
    shift
    case "$sub" in
        check) cmd_check "$@" ;;
        pipeline) cmd_pipeline "$@" ;;
        serve) cmd_serve "$@" ;;
        -h|--help|help) usage; exit 0 ;;
        *)
            err "unknown subcommand: $sub"
            usage
            exit 2
            ;;
    esac
}

main "$@"
