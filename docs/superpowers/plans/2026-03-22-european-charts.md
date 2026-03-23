# European Approach Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add approach charts from 9 European countries to MacheteCharts via a country-plugin architecture, starting with France.

**Architecture:** A unified shell orchestrator (`update-charts.sh`) calls per-country Python modules that each implement a `discover()` function returning airports and chart URLs in a standard format. The orchestrator handles downloading, PDF-to-JPG conversion, JSON merging, and NAS upload. European airports are mixed into the same `charts.json` as US airports with `volume` set to the country code.

**Tech Stack:** Bash (orchestrator), Python 3 (country modules, HTML parsing), ImageMagick (PDF conversion), rsync (NAS upload), curl (downloads)

**Spec:** `docs/superpowers/specs/2026-03-22-european-charts-design.md`

---

## File Structure

### New files to create:
- `scripts/countries/base.py` — Shared utilities: AIRAC cycle calculation, `AIPUnavailableError` exception, `write_outputs()` helper that writes `_download_list.txt` and `charts.json` fragment from a discover() result
- `scripts/countries/faa.py` — US FAA module: downloads d-TPP metafile XML, parses it, returns standard discover() dict
- `scripts/countries/france.py` — France SIA module: scrapes eAIP menu for airport list, scrapes each airport page for chart PDF links
- `scripts/countries/spain.py` — Spain ENAIRE module
- `scripts/countries/netherlands.py` — Netherlands LVNL module
- `scripts/countries/austria.py` — Austria Austro Control module
- `scripts/countries/sweden.py` — Sweden LFV module
- `scripts/countries/uk.py` — UK NATS module
- `scripts/countries/norway.py` — Norway Avinor module
- `scripts/countries/germany.py` — Germany DFS module (experimental)
- `scripts/countries/italy.py` — Italy ENAV module (requires auth)
- `scripts/update-charts.sh` — Unified orchestrator replacing the FAA-specific pipeline

### Files to modify:
- `scripts/update-faa-charts.sh` — Convert to thin wrapper calling `update-charts.sh faa`
- `machete-charts/html_ui/InGamePanels/MacheteCharts/MacheteCharts.html:34,43-44` — Update placeholder and empty state text
- `machete-charts/html_ui/InGamePanels/MacheteCharts/MacheteCharts.js:68-74` — Update clearBtn empty state text

---

## Task 1: Create `base.py` — Shared Utilities

**Files:**
- Create: `scripts/countries/base.py`

- [ ] **Step 1: Create the countries directory and base.py**

```python
"""Shared utilities for MacheteCharts country modules."""

import json
import os
from datetime import date, timedelta

# Known AIRAC effective date (reference epoch)
AIRAC_EPOCH = date(2020, 1, 2)
AIRAC_CYCLE_DAYS = 28


class AIPUnavailableError(Exception):
    """Raised when a country's AIP is unreachable for the requested cycle."""
    pass


def current_airac_date(ref_date=None):
    """Compute the most recent AIRAC effective date on or before ref_date.

    Args:
        ref_date: date to compute from (default: today)

    Returns:
        datetime.date of the AIRAC cycle effective date
    """
    if ref_date is None:
        ref_date = date.today()
    days_since = (ref_date - AIRAC_EPOCH).days
    cycles = days_since // AIRAC_CYCLE_DAYS
    return AIRAC_EPOCH + timedelta(days=cycles * AIRAC_CYCLE_DAYS)


def write_outputs(result, work_dir):
    """Write _download_list.txt and charts.json from a discover() result.

    Args:
        result: dict with "country" key (CLI-friendly name like "france", "faa")
                and "airports" key from discover()
        work_dir: directory to write outputs into (created if needed)

    The "country" key must match the CLI argument / module filename (e.g. "france",
    not "FR") so the orchestrator can find the output files.
    """
    country = result["country"]
    country_dir = os.path.join(work_dir, country)
    os.makedirs(country_dir, exist_ok=True)

    # Write download list: full_url|volume|page_name
    dl_path = os.path.join(country_dir, "_download_list.txt")
    with open(dl_path, "w") as f:
        for code, apt in sorted(result["airports"].items()):
            for cat in ("diagram", "approach", "departure", "star"):
                for plate in apt.get("plates", {}).get(cat, []):
                    f.write(f"{plate['url']}|{apt['volume']}|{plate['page']}\n")

    # Write charts.json fragment (without url fields in plates)
    index = {}
    for code, apt in sorted(result["airports"].items()):
        plates = {}
        for cat in ("diagram", "approach", "departure", "star"):
            cat_plates = apt.get("plates", {}).get(cat, [])
            if cat_plates:
                plates[cat] = [{"name": p["name"], "page": p["page"]} for p in cat_plates]
        if plates:
            index[code] = {
                "code": apt["code"],
                "icao": apt["icao"],
                "name": apt["name"],
                "volume": apt["volume"],
                "plates": plates,
            }

    json_path = os.path.join(country_dir, "charts.json")
    with open(json_path, "w") as f:
        json.dump(index, f, separators=(",", ":"))

    dl_count = sum(
        len(apt.get("plates", {}).get(cat, []))
        for apt in result["airports"].values()
        for cat in ("diagram", "approach", "departure", "star")
    )
    print(f"  {len(index)} airports, {dl_count} charts")
    print(f"  charts.json: {os.path.getsize(json_path) / 1024:.1f} KB")
```

- [ ] **Step 2: Verify it loads without errors**

Run: `cd /Users/todd/Projects/machetecharts && python3 -c "from scripts.countries.base import current_airac_date; print(current_airac_date())"`

If that fails due to import path, test with: `cd /Users/todd/Projects/machetecharts/scripts && python3 -c "from countries.base import current_airac_date; print(current_airac_date())"`

Expected: prints a date like `2026-03-19` (the current AIRAC effective date)

- [ ] **Step 3: Create `__init__.py` for the package**

Create empty `scripts/countries/__init__.py` to make it importable.

- [ ] **Step 4: Commit**

```bash
git add scripts/countries/__init__.py scripts/countries/base.py
git commit -m "Add base.py with shared AIRAC cycle calc and output helpers"
```

---

## Task 2: Create `faa.py` — Refactored FAA Module

**Files:**
- Create: `scripts/countries/faa.py`

This refactors the inline Python from `update-faa-charts.sh` (lines 85-149) into a standalone module following the `discover()` contract.

- [ ] **Step 1: Create faa.py**

```python
"""FAA d-TPP chart discovery module."""

import json
import os
import sys
import xml.etree.ElementTree as ET
from urllib.request import urlopen
from urllib.error import URLError

# Allow running standalone or as module
sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

WANTED = {"APD", "IAP", "DP", "STAR"}
CAT_MAP = {"APD": "diagram", "IAP": "approach", "DP": "departure", "STAR": "star"}


def _cycle_number(cycle_date):
    """Convert AIRAC date to FAA 4-digit cycle number (e.g. 2604).

    FAA uses YYNN format where YY = 2-digit year, NN = cycle number within year.
    """
    year = cycle_date.year
    # Find the first AIRAC date of the year
    from base import AIRAC_EPOCH, AIRAC_CYCLE_DAYS
    from datetime import timedelta

    # Count cycles from epoch to cycle_date
    days = (cycle_date - AIRAC_EPOCH).days
    total_cycle = days // AIRAC_CYCLE_DAYS

    # Count cycles from epoch to Jan 1 of the same year
    jan1 = cycle_date.replace(month=1, day=1)
    days_to_jan1 = (jan1 - AIRAC_EPOCH).days
    first_cycle_of_year = days_to_jan1 // AIRAC_CYCLE_DAYS
    # If jan1 isn't exactly on a cycle boundary, the first cycle starts after it
    if (jan1 - AIRAC_EPOCH).days % AIRAC_CYCLE_DAYS != 0:
        first_cycle_of_year += 1

    nn = total_cycle - first_cycle_of_year + 1
    yy = year % 100
    return f"{yy:02d}{nn:02d}"


def discover(cycle_date, work_dir):
    """Discover FAA d-TPP charts for the given AIRAC cycle.

    Downloads the metafile XML, parses it, and returns the standard dict.
    """
    cycle = _cycle_number(cycle_date)
    base_url = f"https://aeronav.faa.gov/d-tpp/{cycle}/"
    metafile_url = f"{base_url}xml_data/d-tpp_Metafile.xml"

    # Download metafile
    metafile_path = os.path.join(work_dir, "faa", "d-tpp_Metafile.xml")
    os.makedirs(os.path.dirname(metafile_path), exist_ok=True)

    if not os.path.exists(metafile_path):
        print(f"  Downloading {metafile_url}...")
        try:
            with urlopen(metafile_url) as resp:
                data = resp.read()
            with open(metafile_path, "wb") as f:
                f.write(data)
        except URLError as e:
            raise AIPUnavailableError(f"FAA metafile unavailable: {e}")
    else:
        print("  Metafile already cached.")

    # Parse metafile
    tree = ET.parse(metafile_path)
    root = tree.getroot()

    airports = {}

    for state in root.findall("state_code"):
        for city in state.findall("city_name"):
            volume = city.get("volume")
            for apt in city.findall("airport_name"):
                ident = apt.get("apt_ident")
                name = apt.get("ID")
                icao = apt.get("icao_ident", "")
                if ident not in airports:
                    airports[ident] = {
                        "code": ident,
                        "icao": icao,
                        "name": name,
                        "volume": volume,
                        "plates": {
                            "diagram": [],
                            "approach": [],
                            "departure": [],
                            "star": [],
                        },
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
                    url = base_url + pdf
                    airports[ident]["plates"][CAT_MAP[cc]].append(
                        {"name": chart_name, "page": page, "url": url}
                    )

    # Filter to airports that have at least one plate
    result_airports = {}
    for code, apt in sorted(airports.items()):
        has_plates = any(apt["plates"][c] for c in ("diagram", "approach", "departure", "star"))
        if has_plates:
            result_airports[code] = apt

    return {"country": "faa", "airports": result_airports}


if __name__ == "__main__":
    """Standalone usage: python3 faa.py [work_dir] [cycle_number]"""
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"FAA d-TPP: cycle {_cycle_number(cycle_date)} (effective {cycle_date})")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
```

- [ ] **Step 2: Test discovery (dry run — downloads metafile only, no PDFs)**

Run: `cd /Users/todd/Projects/machetecharts/scripts && python3 countries/faa.py /tmp/machete_test`

Expected output:
```
FAA d-TPP: cycle 26XX (effective 2026-03-19)
  Downloading https://aeronav.faa.gov/d-tpp/26XX/xml_data/d-tpp_Metafile.xml...
  ~3193 airports, ~NNNNN charts
  charts.json: ~NNNN.N KB
```

Verify: `ls /tmp/machete_test/faa/` should contain `_download_list.txt`, `charts.json`, and the cached metafile. Spot-check a few lines of `_download_list.txt` to confirm the `full_url|volume|page_name` format.

- [ ] **Step 3: Commit**

```bash
git add scripts/countries/faa.py
git commit -m "Add faa.py country module refactored from update-faa-charts.sh"
```

---

## Task 3: Create `update-charts.sh` — Unified Orchestrator

**Files:**
- Create: `scripts/update-charts.sh`
- Modify: `scripts/update-faa-charts.sh`

- [ ] **Step 1: Create update-charts.sh**

```bash
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
    # FAA uses uppercase country dir name
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
        # Try both .pdf and .PDF extensions for the local file
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
    # Also check uppercase
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

# Load existing data
with open(existing_path) as f:
    merged = json.load(f)

# Determine which volumes are being updated
updating_volumes = set()
for country in countries:
    frag_path = os.path.join(work_dir, country, "charts.json")
    if os.path.exists(frag_path):
        with open(frag_path) as f:
            frag = json.load(f)
        for apt in frag.values():
            updating_volumes.add(apt.get("volume", ""))

# Remove old entries for volumes being updated
merged = {k: v for k, v in merged.items() if v.get("volume", "") not in updating_volumes}

# Insert new entries
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

# Sync JPGs per volume with --delete to clean up removed charts
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
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x /Users/todd/Projects/machetecharts/scripts/update-charts.sh`

- [ ] **Step 3: Convert update-faa-charts.sh to a thin wrapper**

Replace the entire contents of `scripts/update-faa-charts.sh` with:

```bash
#!/bin/bash
#
# update-faa-charts.sh — Thin wrapper for backwards compatibility.
# Delegates to update-charts.sh faa.
#
exec "$(dirname "$0")/update-charts.sh" faa "$@"
```

- [ ] **Step 4: Test the orchestrator help output**

Run: `cd /Users/todd/Projects/machetecharts && ./scripts/update-charts.sh`

Expected: prints usage with available countries (should list `faa` at minimum).

- [ ] **Step 5: Commit**

```bash
git add scripts/update-charts.sh scripts/update-faa-charts.sh
git commit -m "Add unified update-charts.sh orchestrator, convert old script to wrapper"
```

---

## Task 4: Create `france.py` — France SIA Module

**Files:**
- Create: `scripts/countries/france.py`

The French SIA eAIP structure (validated by live testing):
- Menu page at: `{base}/html/eAIP/FR-menu-fr-FR.html` — lists all 141 airports with ICAO codes
- Each airport page at: `{base}/html/eAIP/FR-AD-2.{ICAO}-fr-FR.html` — contains chart links
- Chart PDFs at relative paths like: `Cartes/{ICAO}/AD_2_{ICAO}_{TYPE}_{DETAILS}.pdf`
- Base URL: `https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_{DD}_{MMM}_{YYYY}/FRANCE/AIRAC-{YYYY-MM-DD}/`

Chart type mapping (from LFPG analysis — 245 charts):
- `ADC` → diagram (airport diagram chart)
- `GMC` → diagram (ground movement chart)
- `IAC` → approach (instrument approach chart)
- `SID` → departure
- `STAR` → star
- `APDC`, `AOC`, `PATC`, `COM`, `AMG`, `DATA` → skip (parking, obstacle, pattern, comms, minimum altitude, data tables — not approach plates)

- [ ] **Step 1: Create france.py**

```python
"""France SIA eAIP chart discovery module."""

import os
import re
import sys
from html.parser import HTMLParser
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "FR"

# Chart type prefix -> category mapping
# Only chart types useful as approach plates in the cockpit
CHART_TYPE_MAP = {
    "ADC": "diagram",
    "GMC": "diagram",
    "IAC": "approach",
    "SID": "departure",
    "STAR": "star",
}

# Month abbreviations for URL construction
MONTHS = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]


def _build_base_url(cycle_date):
    """Build the SIA eAIP base URL for the given AIRAC cycle date."""
    dd = cycle_date.day
    mmm = MONTHS[cycle_date.month - 1]
    yyyy = cycle_date.year
    airac_str = cycle_date.strftime("%Y-%m-%d")
    return (
        f"https://www.sia.aviation-civile.gouv.fr/media/dvd/"
        f"eAIP_{dd:02d}_{mmm}_{yyyy}/FRANCE/AIRAC-{airac_str}/"
    )


def _fetch(url):
    """Fetch a URL and return the text content."""
    try:
        with urlopen(url) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"France SIA unavailable: {url} — {e}")


class _MenuParser(HTMLParser):
    """Parse the eAIP menu page to extract airport ICAO codes and names."""

    def __init__(self):
        super().__init__()
        self.airports = []  # list of (icao, name)
        self._in_airport_link = False
        self._current_icao = None
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            m = re.search(r"FR-AD-2\.([A-Z]{4})-fr-FR\.html#AD-2\.eAIP\.", href)
            if m:
                self._in_airport_link = True
                self._current_icao = m.group(1)
                self._text_parts = []

    def handle_data(self, data):
        if self._in_airport_link:
            self._text_parts.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "a" and self._in_airport_link:
            raw_name = " ".join(p for p in self._text_parts if p)
            # Name typically looks like "LFPG PARIS-CHARLES DE GAULLE" — strip the ICAO prefix
            icao = self._current_icao
            name = raw_name
            if name.startswith(icao):
                name = name[len(icao):].strip()
            self.airports.append((icao, name))
            self._in_airport_link = False


def _classify_chart(filename):
    """Classify a chart filename into a category and human-readable name.

    Args:
        filename: e.g. "AD_2_LFPG_IAC_RWY27L_FNA_ILS_CAT123_LOC.pdf"

    Returns:
        (category, name) tuple, or (None, None) if the chart type is not wanted.
    """
    # Strip .pdf and the AD_2_ICAO_ prefix
    base = filename.replace(".pdf", "").replace(".PDF", "")
    # Pattern: AD_2_{ICAO}_{TYPE}_{REST}
    m = re.match(r"AD_2_[A-Z]{4}_(.+)", base)
    if not m:
        return None, None
    rest = m.group(1)

    # Match the chart type prefix
    for prefix, category in CHART_TYPE_MAP.items():
        if rest.startswith(prefix):
            # Build human-readable name from the rest
            name = rest.replace("_", " ")
            return category, name

    return None, None


def discover(cycle_date, work_dir):
    """Discover all French approach charts for the given AIRAC cycle."""
    base_url = _build_base_url(cycle_date)
    eaip_url = base_url + "html/eAIP/"
    menu_url = eaip_url + "FR-menu-fr-FR.html"

    print(f"  Base URL: {base_url}")
    print(f"  Fetching menu...")
    menu_html = _fetch(menu_url)

    parser = _MenuParser()
    parser.feed(menu_html)
    print(f"  Found {len(parser.airports)} airports")

    airports = {}

    for i, (icao, name) in enumerate(parser.airports):
        # Fetch each airport's page to find chart links
        apt_url = eaip_url + f"FR-AD-2.{icao}-fr-FR.html"
        try:
            apt_html = _fetch(apt_url)
        except AIPUnavailableError:
            print(f"  WARNING: Could not fetch {icao}, skipping")
            continue

        # Extract chart PDF links: href="Cartes/{ICAO}/filename.pdf"
        chart_links = re.findall(
            rf'href="Cartes/{icao}/([^"]+\.pdf)"', apt_html, re.IGNORECASE
        )

        plates = {"diagram": [], "approach": [], "departure": [], "star": []}

        for chart_file in chart_links:
            category, chart_name = _classify_chart(chart_file)
            if category is None:
                continue
            page = chart_file.replace(".pdf", "").replace(".PDF", "")
            pdf_url = eaip_url + f"Cartes/{icao}/{chart_file}"
            plates[category].append({
                "name": chart_name,
                "page": page,
                "url": pdf_url,
            })

        # Only include airports with at least one relevant chart
        has_plates = any(plates[c] for c in plates)
        if has_plates:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": name,
                "volume": COUNTRY,
                "plates": plates,
            }

        # Progress + brief delay to avoid rate limiting on SIA servers
        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(parser.airports)} airports...")
            import time
            time.sleep(1)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "france", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"France SIA: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
```

- [ ] **Step 2: Test with a small dry run**

Run: `cd /Users/todd/Projects/machetecharts/scripts && python3 countries/france.py /tmp/machete_test_fr`

This will fetch the menu and all 141 airport pages (takes a few minutes due to HTTP requests). Expected output:
```
France SIA: AIRAC 2026-03-19
  Base URL: https://www.sia.aviation-civile.gouv.fr/media/dvd/eAIP_19_MAR_2026/...
  Fetching menu...
  Found 141 airports
  Processed 20/141 airports...
  ...
  Done: ~141 airports with charts
  141 airports, NNNN charts
  charts.json: NNN.N KB
```

Verify: `head -5 /tmp/machete_test_fr/fr/_download_list.txt` — should show `full_url|FR|page_name` lines.
Verify: `python3 -c "import json; d=json.load(open('/tmp/machete_test_fr/fr/charts.json')); print(list(d.keys())[:5])"` — should show ICAO codes like `['LFBA', 'LFKJ', ...]`.
Spot-check: `curl -sI "$(head -1 /tmp/machete_test_fr/fr/_download_list.txt | cut -d'|' -f1)"` — should return HTTP 200.

- [ ] **Step 3: Commit**

```bash
git add scripts/countries/france.py
git commit -m "Add france.py module for SIA eAIP chart discovery"
```

---

## Task 5: Update JS Plugin Text (Cosmetic Changes)

**Files:**
- Modify: `machete-charts/html_ui/InGamePanels/MacheteCharts/MacheteCharts.html:34,43-44`
- Modify: `machete-charts/html_ui/InGamePanels/MacheteCharts/MacheteCharts.js:68-74`

- [ ] **Step 1: Update MacheteCharts.html**

In `MacheteCharts.html`, make three changes:

Line 34 — search placeholder:
```
OLD: placeholder="Airport ID (e.g. BOS)"
NEW: placeholder="Airport ID (e.g. BOS, LFPG)"
```

Line 43 — empty state heading:
```
OLD: <h2>FAA Terminal Procedures</h2>
NEW: <h2>Terminal Procedures</h2>
```

Line 44 — empty state region:
```
OLD: <div class="region">All US airports</div>
NEW: <div class="region">US & European airports</div>
```

- [ ] **Step 2: Update MacheteCharts.js clearBtn handler**

In `MacheteCharts.js`, lines 68-74 — update the hardcoded strings in the clearBtn click handler:

```
OLD: '<h2>FAA Terminal Procedures</h2>' +
NEW: '<h2>Terminal Procedures</h2>' +

OLD: '<div class="region">All US airports</div>' +
NEW: '<div class="region">US & European airports</div>' +
```

- [ ] **Step 3: Fix on-screen keyboard character limit**

In `MacheteCharts.js`, line 144 — the on-screen keyboard blocks typing the 4th character because the condition is `< 4` (allows 0-3 length, meaning only 3 chars can be entered). European ICAO codes are 4 characters. Change:

```
OLD: } else if (searchInput.value.length < 4) {
NEW: } else if (searchInput.value.length < 5) {
```

Also update `maxlength` in `MacheteCharts.html` line 34 to match:

```
OLD: maxlength="4"
NEW: maxlength="5"
```

This allows both 3-letter FAA codes and 4-letter ICAO codes, plus a small buffer.

- [ ] **Step 4: Commit**

```bash
git add machete-charts/html_ui/InGamePanels/MacheteCharts/MacheteCharts.html
git add machete-charts/html_ui/InGamePanels/MacheteCharts/MacheteCharts.js
git commit -m "Update plugin text and input limits for international chart support"
```

---

## Task 6: Create `spain.py` — Spain ENAIRE Module

**Files:**
- Create: `scripts/countries/spain.py`

Spain's ENAIRE has the cleanest URL structure of all countries — stable URLs with no AIRAC date in the path:
- Airport pages: `https://aip.enaire.es/aip/contenido_AIP/AD/AD2/{ICAO}/`
- Chart PDFs: `https://aip.enaire.es/aip/contenido_AIP/AD/AD2/{ICAO}/LE_AD_2_{ICAO}_{TYPE}_{NUM}_en.pdf`
- AIP index: `https://aip.enaire.es/aip/aip-en.html`

- [ ] **Step 1: Create spain.py**

The module should:
1. Fetch the AIP index HTML at `https://aip.enaire.es/aip/aip-en.html`
2. Parse it to extract all Spanish airport ICAO codes (LE** prefix) and names
3. For each airport, fetch `https://aip.enaire.es/aip/contenido_AIP/AD/AD2/{ICAO}/` or the airport's HTML page
4. Extract chart PDF links
5. Classify chart types (IAC → approach, SID → departure, STAR → star, ADC → diagram)
6. Return the standard discover() dict with `country: "spain"` and `volume: "ES"` on each airport

Use the same pattern as `france.py`. The chart filename pattern is `LE_AD_2_{ICAO}_{TYPE}_{NUM}_en.pdf`.

**Important:** Since ENAIRE uses stable URLs (no AIRAC date), the module can construct chart URLs more directly than France. However, the AIP index page structure needs to be scraped first to discover airports.

Run standalone test: `cd /Users/todd/Projects/machetecharts/scripts && python3 countries/spain.py /tmp/machete_test_es`

Verify: check that `_download_list.txt` and `charts.json` are populated and URLs return HTTP 200.

- [ ] **Step 2: Commit**

```bash
git add scripts/countries/spain.py
git commit -m "Add spain.py module for ENAIRE AIP chart discovery"
```

---

## Task 7: Create `netherlands.py` — Netherlands LVNL Module

**Files:**
- Create: `scripts/countries/netherlands.py`

Netherlands LVNL eAIP structure:
- Base: `https://eaip.lvnl.nl/web/eaip/`
- Chart paths: `AIRAC%20AMDT%20{NN}-{YYYY}_{YYYY}_{MM}_{DD}/documents/Root_WePub/Charts/AD/{ICAO}/{ICAO}-{TYPE}-{NUM}-{PROCEDURE}.pdf`
- The AIRAC amendment number increments each cycle and needs to be discovered from the index page

- [ ] **Step 1: Create netherlands.py**

The module should:
1. Fetch the LVNL eAIP default page to discover the current AIRAC amendment path
2. Parse the airport list
3. For each airport, discover chart PDFs
4. Classify chart types (IAC → approach, SID → departure, STAR → star, ADC → diagram)
5. Return standard discover() dict with `country: "netherlands"` and `volume: "NL"` on each airport

Run standalone test: `cd /Users/todd/Projects/machetecharts/scripts && python3 countries/netherlands.py /tmp/machete_test_nl`

- [ ] **Step 2: Commit**

```bash
git add scripts/countries/netherlands.py
git commit -m "Add netherlands.py module for LVNL eAIP chart discovery"
```

---

## Task 8: Create `austria.py` — Austria Austro Control Module

**Files:**
- Create: `scripts/countries/austria.py`

Austria Austro Control eAIP structure:
- Base: `https://eaip.austrocontrol.at/lo/{YYMMDD}/`
- Charts: `Charts/{ICAO}/LO_AD_2_{ICAO}_{SECTION}_en.pdf`
- Date format in URL: `YYMMDD` (e.g. `260319` for 2026-03-19)

- [ ] **Step 1: Create austria.py**

The module should:
1. Construct the base URL from the AIRAC cycle date using `YYMMDD` format
2. Fetch the index/menu page to discover airports
3. For each airport, discover chart PDFs from the `Charts/{ICAO}/` directory
4. Classify chart types using AIP section numbers (section 24 = charts area)
5. Return standard discover() dict with `country: "austria"` and `volume: "AT"` on each airport

Run standalone test: `cd /Users/todd/Projects/machetecharts/scripts && python3 countries/austria.py /tmp/machete_test_at`

- [ ] **Step 2: Commit**

```bash
git add scripts/countries/austria.py
git commit -m "Add austria.py module for Austro Control eAIP chart discovery"
```

---

## Task 9: Create Tier 2 Country Modules (UK, Sweden, Norway)

**Files:**
- Create: `scripts/countries/uk.py`
- Create: `scripts/countries/sweden.py`
- Create: `scripts/countries/norway.py`

These countries require scraping an index page to discover opaque chart IDs.

- [ ] **Step 1: Create uk.py**

UK NATS eAIP structure:
- Base: `https://www.aurora.nats.co.uk/htmlAIP/Publications/{YYYY-MM-DD}-AIRAC/`
- Airport pages: `html/eAIP/EG-AD-2.{ICAO}-en-GB.html` — contains references to chart PDFs
- Chart PDFs: `graphics/{NUMERIC_ID}.pdf` — opaque numeric IDs, must be scraped from airport pages
- Volume: `"GB"`

Must scrape each airport HTML page to discover the numeric chart PDF IDs.

- [ ] **Step 2: Create sweden.py**

Sweden LFV eAIP structure:
- Base: `https://aro.lfv.se/content/eaip/`
- AIRAC path: `AIRAC%20AIP%20AMDT%20{N}-{YYYY}_{YYYY}_{MM}_{DD}/`
- Chart naming: `ES_AD_2_{ICAO}_{SECTION}_en.pdf`
- Volume: `"SE"`

- [ ] **Step 3: Create norway.py**

Norway Avinor eAIP structure:
- Base: `https://aim-prod.avinor.no/no/AIP/View/Index/{INDEX_NUM}/{YYYY-MM-DD}-AIRAC/`
- Chart PDFs: `graphics/{NUMERIC_ID}.pdf` — opaque numeric IDs
- Must discover the Index number and scrape airport pages for chart IDs
- Volume: `"NO"`

- [ ] **Step 4: Test each module standalone**

```bash
cd /Users/todd/Projects/machetecharts/scripts
python3 countries/uk.py /tmp/machete_test_gb
python3 countries/sweden.py /tmp/machete_test_se
python3 countries/norway.py /tmp/machete_test_no
```

- [ ] **Step 5: Commit**

```bash
git add scripts/countries/uk.py scripts/countries/sweden.py scripts/countries/norway.py
git commit -m "Add Tier 2 country modules: UK, Sweden, Norway"
```

---

## Task 10: Create Tier 3 Country Modules (Germany, Italy)

**Files:**
- Create: `scripts/countries/germany.py`
- Create: `scripts/countries/italy.py`

These are optional/experimental — they only run if credentials are configured.

- [ ] **Step 1: Create germany.py**

Germany DFS eAIP structure:
- Base: `https://aip.dfs.de/BasicIFR/{YYYY}{Mmm}{DD}/` (e.g. `2026Mar19`)
- Pages use hex hash IDs — must scrape the full table of contents to map ICAO codes to hashes
- Volume: `"DE"`
- **Experimental:** hashes change every cycle, high maintenance

Returns `None` if scraping fails (graceful degradation).

- [ ] **Step 2: Create italy.py**

Italy ENAV eAIP:
- Requires free registration at `https://www.enav.it/en/user/register`
- Checks env vars `MACHETE_ENAV_USER` and `MACHETE_ENAV_PASS`
- Returns `None` if credentials not configured
- Volume: `"IT"`
- Needs session-based authentication with re-auth on token expiry

- [ ] **Step 3: Commit**

```bash
git add scripts/countries/germany.py scripts/countries/italy.py
git commit -m "Add Tier 3 country modules: Germany (experimental), Italy (auth required)"
```

---

## Task 11: End-to-End Integration Test

- [ ] **Step 1: Run orchestrator with France only**

```bash
cd /Users/todd/Projects/machetecharts
export MACHETE_NAS_HOST="user@your-nas-ip"
./scripts/update-charts.sh france
```

Verify all 6 steps complete successfully. Check that:
- `charts.json` on NAS contains both US (existing) and French airports
- JPGs exist at `/volume1/web/MacheteCharts/charts/FR/` on the NAS
- A chart URL resolves: `curl -sI "https://hermes-tv.com/MacheteCharts/charts/FR/AD_2_LFPG_IAC_RWY27L_FNA_ILS_CAT123_LOC.jpg"`

- [ ] **Step 2: Test in MSFS plugin**

Open MacheteCharts in MSFS. Search for "LFPG". Verify:
- Airport appears in search results
- Categories show approach, departure, star, diagram
- Chart images load and display correctly
- Zooming/panning works
- US airports (BOS, JFK) still work

- [ ] **Step 3: Run orchestrator with all Tier 1 countries**

```bash
./scripts/update-charts.sh france,spain,netherlands,austria
```

Verify merged charts.json contains all countries. Spot-check a few airports from each country.

- [ ] **Step 4: Run FAA backwards-compatibility check**

```bash
./scripts/update-faa-charts.sh
```

Verify it delegates to `update-charts.sh faa` and completes successfully.
