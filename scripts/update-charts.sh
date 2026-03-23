#!/bin/bash
#
# update-charts.sh — Unified chart update orchestrator.
#
# Downloads charts from one or more country sources, converts PDFs to JPGs,
# merges into a single charts.json, and uploads to the NAS.
#
# Usage:
#   ./scripts/update-charts.sh faa              # US only
#   ./scripts/update-charts.sh france           # France only
#   ./scripts/update-charts.sh france,spain     # multiple countries
#   ./scripts/update-charts.sh --all            # all available country modules
#
# Requirements: python3, magick (ImageMagick), ghostscript, rsync, curl

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COUNTRIES_DIR="${SCRIPT_DIR}/countries"

# ── Configuration ──
NAS_HOST="${MACHETE_NAS_HOST:?Set MACHETE_NAS_HOST (e.g. user@192.168.1.10)}"
NAS_CHARTS_DIR="${MACHETE_NAS_CHARTS_DIR:-/volume1/web/MacheteCharts/charts}"
NAS_JSON_PATH="${MACHETE_NAS_JSON_PATH:-/volume1/web/MacheteCharts/charts.json}"
WORK_DIR="/tmp/machete_charts"
DPI=150
JPG_QUALITY=85
PARALLEL_DOWNLOADS=12
PARALLEL_CONVERT=6

# ── Parse arguments ──
if [ -z "${1:-}" ]; then
    echo "Usage: $0 <country|country,country|--all>"
    echo ""
    echo "Available countries:"
    for f in "$COUNTRIES_DIR"/*.py; do
        name=$(basename "$f" .py)
        [ "$name" = "base" ] || [ "$name" = "__init__" ] && continue
        echo "  $name"
    done
    exit 1
fi

COUNTRIES=()
if [ "$1" = "--all" ]; then
    for f in "$COUNTRIES_DIR"/*.py; do
        name=$(basename "$f" .py)
        [ "$name" = "base" ] || [ "$name" = "__init__" ] && continue
        COUNTRIES+=("$name")
    done
else
    IFS=',' read -ra COUNTRIES <<< "$1"
fi

echo "=== MacheteCharts Update ==="
echo "  Countries: ${COUNTRIES[*]}"
echo ""

# ── Check dependencies ──
for cmd in python3 magick gs rsync curl; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: $cmd is required but not found."
        [ "$cmd" = "magick" ] && echo "  Install: brew install imagemagick"
        [ "$cmd" = "gs" ] && echo "  Install: brew install ghostscript"
        exit 1
    fi
done

# ── Check NAS connectivity ──
NAS_IP=$(echo "$NAS_HOST" | cut -d@ -f2)
if ! ping -c 1 -t 3 "$NAS_IP" &>/dev/null; then
    echo "ERROR: NAS at $NAS_IP is not reachable."
    exit 1
fi

mkdir -p "$WORK_DIR"

# ── Step 1: Download existing charts.json from NAS ──
echo "=== Step 1: Fetch existing charts.json from NAS ==="
EXISTING_JSON="${WORK_DIR}/existing_charts.json"
if scp -q "${NAS_HOST}:${NAS_JSON_PATH}" "$EXISTING_JSON" 2>/dev/null; then
    EXISTING_COUNT=$(python3 -c "import json; print(len(json.load(open('$EXISTING_JSON'))))")
    echo "  Loaded $EXISTING_COUNT existing airports."
else
    echo "  No existing charts.json on NAS (fresh install)."
    echo "{}" > "$EXISTING_JSON"
fi

# ── Step 2: Run discovery for each country ──
echo ""
echo "=== Step 2: Discover charts ==="
SUCCESSFUL_COUNTRIES=()
for country in "${COUNTRIES[@]}"; do
    module="${COUNTRIES_DIR}/${country}.py"
    if [ ! -f "$module" ]; then
        echo "  WARNING: No module found for '$country', skipping."
        continue
    fi
    echo ""
    echo "--- $country ---"
    if python3 "$module" "$WORK_DIR"; then
        SUCCESSFUL_COUNTRIES+=("$country")
    else
        echo "  WARNING: $country failed, continuing with others."
    fi
done

if [ ${#SUCCESSFUL_COUNTRIES[@]} -eq 0 ]; then
    echo ""
    echo "ERROR: No countries succeeded. Nothing to do."
    exit 1
fi

echo ""
echo "  Successful: ${SUCCESSFUL_COUNTRIES[*]}"

# ── Step 3: Combine download lists and download PDFs ──
echo ""
echo "=== Step 3: Download PDFs ==="
COMBINED_DL="${WORK_DIR}/_combined_download_list.txt"
> "$COMBINED_DL"

PDF_DIR="${WORK_DIR}/pdfs"
JPG_DIR="${WORK_DIR}/jpgs"
mkdir -p "$PDF_DIR" "$JPG_DIR"

for country in "${SUCCESSFUL_COUNTRIES[@]}"; do
    dl_file="${WORK_DIR}/${country}/_download_list.txt"
    if [ -f "$dl_file" ]; then
        cat "$dl_file" >> "$COMBINED_DL"
    fi
done

TOTAL=$(wc -l < "$COMBINED_DL" | tr -d ' ')
echo "  Total charts to check: $TOTAL"

# Create volume directories
cut -d'|' -f2 "$COMBINED_DL" | sort -u | while read -r vol; do
    mkdir -p "$PDF_DIR/$vol" "$JPG_DIR/$vol"
done

# Count already downloaded
EXISTING_PDFS=$(find "$PDF_DIR" -name "*.pdf" -o -name "*.PDF" 2>/dev/null | wc -l | tr -d ' ')
echo "  Already cached: $EXISTING_PDFS"

if [ "$TOTAL" -gt 0 ]; then
    echo "  Downloading with $PARALLEL_DOWNLOADS parallel workers..."
    cat "$COMBINED_DL" | xargs -P "$PARALLEL_DOWNLOADS" -I {} /bin/bash -c '
        IFS="|" read -r url vol page <<< "$1"
        dest="'"$PDF_DIR"'/$vol/$page.pdf"
        dest_upper="'"$PDF_DIR"'/$vol/$page.PDF"
        [ -f "$dest" ] && [ -s "$dest" ] && exit 0
        [ -f "$dest_upper" ] && [ -s "$dest_upper" ] && exit 0
        for attempt in 1 2 3; do
            curl -sf -o "$dest" "$url" && echo "OK" && exit 0
            sleep $attempt
        done
        echo "FAIL:$page"
    ' _ {} 2>&1 | awk '
        BEGIN{ok=0;fail=0}
        /^OK/{ok++}
        /^FAIL:/{fail++; print "  WARNING: " $0}
        (ok+fail)%1000==0 && (ok+fail)>0 {printf "  %d downloaded...\n", ok+fail}
        END{printf "  Download complete: %d ok, %d failed\n", ok, fail}
    '
fi

# ── Step 4: Convert PDFs to JPGs ──
echo ""
echo "=== Step 4: Convert PDFs to JPGs ==="

WORKLIST="${WORK_DIR}/_convert_worklist.txt"
> "$WORKLIST"
converted=0
need_convert=0

while IFS='|' read -r url vol page; do
    pdf="$PDF_DIR/$vol/$page.pdf"
    [ ! -f "$pdf" ] && pdf="$PDF_DIR/$vol/$page.PDF"
    jpg="$JPG_DIR/$vol/$page.jpg"
    if [ -f "$jpg" ] && [ -s "$jpg" ]; then
        converted=$((converted + 1))
    elif [ -f "$pdf" ] && [ -s "$pdf" ]; then
        echo "$pdf|$jpg" >> "$WORKLIST"
        need_convert=$((need_convert + 1))
    fi
done < "$COMBINED_DL"

echo "  Already converted: $converted, Need conversion: $need_convert"

if [ "$need_convert" -gt 0 ]; then
    echo "  Converting with $PARALLEL_CONVERT parallel workers (DPI=$DPI, quality=$JPG_QUALITY)..."
    cat "$WORKLIST" | xargs -P "$PARALLEL_CONVERT" -I {} /bin/bash -c '
        IFS="|" read -r pdf jpg <<< "$1"
        magick -density '"$DPI"' "${pdf}[0]" -background white -alpha remove -quality '"$JPG_QUALITY"' "$jpg" 2>/dev/null
        if [ $? -eq 0 ]; then echo "OK"; else echo "FAIL"; fi
    ' _ {} 2>&1 | awk '
        BEGIN{ok=0;fail=0}
        /^OK/{ok++}
        /^FAIL/{fail++}
        (ok+fail)%1000==0 && (ok+fail)>0 {printf "  %d converted...\n", ok+fail}
        END{printf "  Conversion complete: %d ok, %d failed\n", ok, fail}
    '
fi

# ── Step 5: Merge charts.json ──
echo ""
echo "=== Step 5: Merge charts.json ==="
MERGED_JSON="${WORK_DIR}/charts.json"

python3 - "$EXISTING_JSON" "$MERGED_JSON" "${SUCCESSFUL_COUNTRIES[*]}" "$WORK_DIR" <<'PYEOF'
import json, sys, os

existing_path = sys.argv[1]
merged_path = sys.argv[2]
countries = sys.argv[3].split()
work_dir = sys.argv[4]

with open(existing_path) as f:
    merged = json.load(f)

updating_volumes = set()
for country in countries:
    frag_path = os.path.join(work_dir, country, "charts.json")
    if os.path.exists(frag_path):
        with open(frag_path) as f:
            frag = json.load(f)
        for apt in frag.values():
            updating_volumes.add(apt.get("volume", ""))

merged = {k: v for k, v in merged.items() if v.get("volume", "") not in updating_volumes}

for country in countries:
    frag_path = os.path.join(work_dir, country, "charts.json")
    if os.path.exists(frag_path):
        with open(frag_path) as f:
            frag = json.load(f)
        merged.update(frag)

with open(merged_path, "w") as f:
    json.dump(merged, f, separators=(",", ":"))

print(f"  Merged: {len(merged)} airports total")
print(f"  Updated volumes: {', '.join(sorted(updating_volumes))}")
print(f"  Size: {os.path.getsize(merged_path) / 1024 / 1024:.1f} MB")
PYEOF

# ── Step 6: Upload to NAS ──
echo ""
echo "=== Step 6: Upload to NAS ==="

for country in "${SUCCESSFUL_COUNTRIES[@]}"; do
    frag_path="${WORK_DIR}/${country}/charts.json"
    [ -f "$frag_path" ] || continue
    vols=$(python3 -c "import json; print(' '.join(set(a['volume'] for a in json.load(open('$frag_path')).values())))")
    for vol in $vols; do
        if [ -d "$JPG_DIR/$vol" ]; then
            echo "  Syncing $vol..."
            rsync -a --delete --info=progress2 "$JPG_DIR/$vol/" "${NAS_HOST}:${NAS_CHARTS_DIR}/$vol/"
        fi
    done
done

echo ""
echo "  Uploading charts.json..."
rsync -a "$MERGED_JSON" "${NAS_HOST}:${NAS_JSON_PATH}"

# ── Done ──
echo ""
echo "=== Done ==="
TOTAL_AIRPORTS=$(python3 -c "import json; print(len(json.load(open('$MERGED_JSON'))))")
echo "  Countries: ${SUCCESSFUL_COUNTRIES[*]}"
echo "  Total airports: $TOTAL_AIRPORTS"
echo "  NAS: $NAS_HOST"
echo ""
echo "  Cached files in ${WORK_DIR}/"
