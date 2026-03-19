#!/bin/bash
#
# update-faa-charts.sh — Download current FAA d-TPP charts, convert to JPG,
# build charts.json, and upload to the NAS.
#
# Usage:
#   ./scripts/update-faa-charts.sh           # auto-detect current cycle
#   ./scripts/update-faa-charts.sh 2604      # specify cycle explicitly
#
# Requirements: python3, magick (ImageMagick), ghostscript, rsync
#
# FAA d-TPP cycles are 28 days. Check https://aeronav.faa.gov/d-tpp/ for
# available cycles. New cycle PDFs are usually posted a few days before
# the effective date.

set -euo pipefail

# ── Configuration ──
NAS_HOST="todd@192.168.1.10"
NAS_CHARTS_DIR="/volume1/web/MacheteCharts/charts"
NAS_JSON_PATH="/volume1/web/MacheteCharts/charts.json"
WORK_DIR="/tmp/faa_dtpp"
DPI=150
JPG_QUALITY=85
PARALLEL_DOWNLOADS=12
PARALLEL_CONVERT=6

# ── Determine cycle ──
if [ -n "${1:-}" ]; then
    CYCLE="$1"
    echo "Using specified cycle: $CYCLE"
else
    echo "Auto-detecting current FAA d-TPP cycle..."
    # Fetch directory listing and find the latest 26xx cycle
    CYCLE=$(curl -s "https://aeronav.faa.gov/d-tpp/" | \
        grep -oE '26[0-9]{2}/' | tr -d '/' | sort -n | tail -1)
    if [ -z "$CYCLE" ]; then
        echo "ERROR: Could not auto-detect cycle. Specify manually: $0 2604"
        exit 1
    fi
    echo "Detected cycle: $CYCLE"
fi

BASE_URL="https://aeronav.faa.gov/d-tpp/${CYCLE}/"
METAFILE_URL="${BASE_URL}xml_data/d-tpp_Metafile.xml"

PDF_DIR="${WORK_DIR}/${CYCLE}/pdfs"
JPG_DIR="${WORK_DIR}/${CYCLE}/jpgs"
METAFILE="${WORK_DIR}/${CYCLE}/d-tpp_Metafile.xml"
CHARTS_JSON="${WORK_DIR}/${CYCLE}/charts.json"

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
if ! ping -c 1 -t 3 192.168.1.10 &>/dev/null; then
    echo "ERROR: NAS at 192.168.1.10 is not reachable."
    exit 1
fi

mkdir -p "${WORK_DIR}/${CYCLE}"

# ── Step 1: Download metafile ──
echo ""
echo "=== Step 1: Download metafile ==="
if [ -f "$METAFILE" ]; then
    echo "  Metafile already cached."
else
    echo "  Downloading ${METAFILE_URL}..."
    curl -sL -o "$METAFILE" "$METAFILE_URL"
    echo "  Done ($(du -h "$METAFILE" | cut -f1))."
fi

# ── Step 2: Parse metafile and build download list ──
echo ""
echo "=== Step 2: Parse metafile ==="
python3 - "$METAFILE" "$PDF_DIR" "$CHARTS_JSON" <<'PYEOF'
import xml.etree.ElementTree as ET
import json, os, sys

METAFILE = sys.argv[1]
PDF_DIR = sys.argv[2]
CHARTS_JSON = sys.argv[3]

WANTED = {"APD", "IAP", "DP", "STAR"}
CAT_MAP = {"APD": "diagram", "IAP": "approach", "DP": "departure", "STAR": "star"}

tree = ET.parse(METAFILE)
root = tree.getroot()

airports = {}
pdfs = {}  # pdf_name -> volume

for state in root.findall("state_code"):
    for city in state.findall("city_name"):
        volume = city.get("volume")
        for apt in city.findall("airport_name"):
            ident = apt.get("apt_ident")
            name = apt.get("ID")
            icao = apt.get("icao_ident", "")
            if ident not in airports:
                airports[ident] = {
                    "code": ident, "icao": icao, "name": name, "volume": volume,
                    "plates": {"diagram": [], "approach": [], "departure": [], "star": []}
                }
            for rec in apt.findall("record"):
                cc = rec.find("chart_code").text
                if cc not in WANTED:
                    continue
                pdf = rec.find("pdf_name").text
                chart_name = rec.find("chart_name").text
                if not pdf:
                    continue
                page = pdf.replace(".PDF", "").replace(".pdf", "")
                airports[ident]["plates"][CAT_MAP[cc]].append({"name": chart_name, "page": page})
                pdfs[pdf] = volume

# Build charts.json
index = {}
for code, apt in sorted(airports.items()):
    plates = {c: apt["plates"][c] for c in ["diagram","approach","departure","star"] if apt["plates"][c]}
    if plates:
        index[code] = {"code": code, "icao": apt.get("icao",""), "name": apt["name"],
                       "volume": apt["volume"], "plates": plates}

with open(CHARTS_JSON, "w") as f:
    json.dump(index, f, separators=(",", ":"))

# Write download list
os.makedirs(PDF_DIR, exist_ok=True)
with open(PDF_DIR + "/_download_list.txt", "w") as f:
    for pdf, vol in sorted(pdfs.items()):
        f.write(f"{pdf}|{vol}\n")

# Create volume dirs
for vol in set(pdfs.values()):
    os.makedirs(os.path.join(PDF_DIR, vol), exist_ok=True)

print(f"  {len(index)} airports, {len(pdfs)} charts")
print(f"  charts.json: {os.path.getsize(CHARTS_JSON) / 1024 / 1024:.1f} MB")
PYEOF

# ── Step 3: Download PDFs ──
echo ""
echo "=== Step 3: Download PDFs ==="
DOWNLOAD_LIST="${PDF_DIR}/_download_list.txt"
TOTAL=$(wc -l < "$DOWNLOAD_LIST")

# Count already downloaded
EXISTING=$(find "$PDF_DIR" -name "*.PDF" 2>/dev/null | wc -l | tr -d ' ')
NEED=$((TOTAL - EXISTING))
echo "  Total: $TOTAL, Already have: $EXISTING, Need: $NEED"

if [ "$NEED" -gt 0 ]; then
    echo "  Downloading with $PARALLEL_DOWNLOADS parallel workers..."
    cat "$DOWNLOAD_LIST" | xargs -P "$PARALLEL_DOWNLOADS" -I {} /bin/bash -c '
        IFS="|" read -r pdf vol <<< "$1"
        dest="'"$PDF_DIR"'/$vol/$pdf"
        [ -f "$dest" ] && [ -s "$dest" ] && exit 0
        for attempt in 1 2 3; do
            curl -sf -o "$dest" "'"$BASE_URL"'$pdf" && echo "OK" && exit 0
            sleep $attempt
        done
        echo "FAIL:$pdf"
    ' _ {} 2>&1 | awk '
        BEGIN{ok=0;fail=0}
        /^OK/{ok++}
        /^FAIL:/{fail++; print "  WARNING: " $0}
        (ok+fail)%1000==0 && (ok+fail)>0 {printf "  %d downloaded...\n", ok+fail}
        END{printf "  Download complete: %d ok, %d failed\n", ok, fail}
    '
else
    echo "  All PDFs already cached."
fi

# ── Step 4: Convert PDFs to JPGs ──
echo ""
echo "=== Step 4: Convert PDFs to JPGs ==="

# Create volume dirs in JPG output
for vol_dir in "$PDF_DIR"/*/; do
    [ -d "$vol_dir" ] || continue
    vol=$(basename "$vol_dir")
    mkdir -p "$JPG_DIR/$vol"
done

# Build worklist of unconverted files
WORKLIST="${WORK_DIR}/${CYCLE}/_convert_worklist.txt"
> "$WORKLIST"
converted=0
need_convert=0

while IFS='|' read -r pdf vol; do
    base="${pdf%.PDF}"
    base="${base%.pdf}"
    jpg="$JPG_DIR/$vol/$base.jpg"
    if [ -f "$jpg" ] && [ -s "$jpg" ]; then
        converted=$((converted + 1))
    else
        echo "$PDF_DIR/$vol/$pdf|$jpg" >> "$WORKLIST"
        need_convert=$((need_convert + 1))
    fi
done < "$DOWNLOAD_LIST"

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
else
    echo "  All JPGs already cached."
fi

JPG_COUNT=$(find "$JPG_DIR" -name "*.jpg" | wc -l | tr -d ' ')
JPG_SIZE=$(du -sh "$JPG_DIR" | cut -f1)
echo "  Total JPGs: $JPG_COUNT ($JPG_SIZE)"

# ── Step 5: Upload to NAS ──
echo ""
echo "=== Step 5: Upload to NAS ==="
echo "  Syncing JPGs to ${NAS_HOST}:${NAS_CHARTS_DIR}/"
rsync -a --info=progress2 "$JPG_DIR/" "${NAS_HOST}:${NAS_CHARTS_DIR}/"
echo ""
echo "  Uploading charts.json..."
rsync -a "$CHARTS_JSON" "${NAS_HOST}:${NAS_JSON_PATH}"

# ── Step 6: Clean up old flat files on NAS (if any) ──
echo ""
echo "=== Step 6: Clean up old files ==="
OLD_COUNT=$(ssh "$NAS_HOST" "find ${NAS_CHARTS_DIR} -maxdepth 1 -name '*.jpg' 2>/dev/null | wc -l" | tr -d ' ')
if [ "$OLD_COUNT" -gt 0 ]; then
    echo "  Removing $OLD_COUNT old flat JPGs from NAS..."
    ssh "$NAS_HOST" "find ${NAS_CHARTS_DIR} -maxdepth 1 -name '*.jpg' -delete"
else
    echo "  No old files to clean up."
fi

# ── Done ──
echo ""
echo "=== Done ==="
echo "  Cycle: $CYCLE"
echo "  Airports: $(python3 -c "import json; print(len(json.load(open('$CHARTS_JSON'))))")"
echo "  Charts: $JPG_COUNT"
echo "  NAS: http://192.168.1.10/MacheteCharts/"
echo ""
echo "  Cached files are in ${WORK_DIR}/${CYCLE}/"
echo "  To free disk space: rm -rf ${WORK_DIR}/${CYCLE}/pdfs"
