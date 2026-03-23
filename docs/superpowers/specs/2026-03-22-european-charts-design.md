# European Approach Charts Integration

## Overview

Add approach charts from European countries to MacheteCharts, alongside the existing FAA (US) charts. European charts come from free government-published AIPs (Aeronautical Information Publications), following the same 28-day AIRAC cycle as the FAA.

## Goals

- Ingest approach plates (IAP, SID, STAR, airport diagrams) from up to 9 European countries
- Mix European airports into the same unified search as US airports
- Require zero changes to the MSFS plugin logic (only cosmetic text updates)
- Design a country-plugin architecture that makes adding new countries straightforward

## Data Model

Each airport entry in `charts.json` follows the existing schema:

```json
"LFPG": {
  "code": "LFPG",
  "icao": "LFPG",
  "name": "PARIS-CHARLES DE GAULLE",
  "volume": "FR",
  "plates": {
    "diagram": [{"name": "ADC", "page": "AD_2_LFPG_ADC_1"}],
    "approach": [{"name": "ILS RWY 27L", "page": "AD_2_LFPG_IAC_1"}],
    "departure": [{"name": "SID RWY 27", "page": "AD_2_LFPG_SID_1"}],
    "star": [{"name": "STAR RWY 27", "page": "AD_2_LFPG_STAR_1"}]
  }
}
```

Key points:
- `code` and `icao` are the same for European airports (they use ICAO codes natively)
- `volume` is set to the 2-letter country code (FR, ES, NL, AT, GB, SE, NO, DE, IT)
- The existing JS builds image URLs as `charts/{volume}/{page}.jpg`, so no plugin logic changes needed
- `plates` categories are the same four buckets: diagram, approach, departure, star
- The existing `normalizeCode()` K-prefix stripping still works — European codes don't start with K
- `page` names only need to be unique within their `volume` directory, not globally — the volume-based NAS directory structure prevents cross-country file collisions
- Adding 9 European countries will roughly double the size of `charts.json` (currently 1.2 MB for ~3,200 US airports). This remains well within acceptable limits for the MSFS Coherent GT browser to fetch and parse

## Script Architecture

### File Layout

```
scripts/
  update-charts.sh              # unified orchestrator
  update-faa-charts.sh          # kept as thin wrapper: exec update-charts.sh faa "$@"
  countries/
    base.py                     # shared: AIRAC cycle calc, discover() contract, download list output
    faa.py                      # US (refactored from current bash parsing logic)
    france.py                   # SIA eAIP
    spain.py                    # ENAIRE
    netherlands.py              # LVNL
    austria.py                  # Austro Control
    sweden.py                   # LFV
    uk.py                       # NATS (scrapes index for numeric chart IDs)
    norway.py                   # Avinor (scrapes index for numeric chart IDs)
    germany.py                  # DFS (scrapes TOC for hex hash IDs)
    italy.py                    # ENAV (requires free registration + auth)
```

### Orchestrator Flow (update-charts.sh)

Usage:
```bash
./scripts/update-charts.sh france          # single country
./scripts/update-charts.sh france,spain    # multiple countries
./scripts/update-charts.sh --all           # discovers all .py files in countries/ (except base.py)
./scripts/update-charts.sh faa             # just US (backwards-compatible)
```

Steps:
1. Parse arguments, determine which countries to run
2. Download current `charts.json` from NAS (to preserve data for countries not being updated)
3. For each country, call `python3 countries/{country}.py` which outputs:
   - `{work_dir}/{country}/_download_list.txt` — download list (see format below)
   - `{work_dir}/{country}/charts.json` — airport index fragment for that country
4. Parallel PDF download (reuses existing xargs/curl pattern)
5. Parallel PDF-to-JPG conversion — first page only (`[0]`), same as FAA pipeline. Multi-page PDFs are common in European AIPs (e.g. textual descriptions on page 2) but only the graphical chart on page 1 is needed.
6. Merge all country `charts.json` fragments with preserved data into one unified `charts.json`
7. Rsync JPGs and merged `charts.json` to NAS — uses `rsync --delete` within each volume directory being updated, so charts removed between AIRAC cycles are cleaned up. Volumes not being updated are untouched.

### Download List Format

Each country module writes `_download_list.txt` with the format:
```
full_url|volume|page_name
```
Example (France):
```
https://www.sia.aviation-civile.gouv.fr/.../AD_2_LFPG_IAC_1.pdf|FR|AD_2_LFPG_IAC_1
```
Example (FAA):
```
https://aeronav.faa.gov/d-tpp/2604/00085IL27L.PDF|NE-1|00085IL27L
```
The orchestrator downloads each URL to `{work_dir}/{volume}/{page_name}.pdf`, then converts to `{jpg_dir}/{volume}/{page_name}.jpg`. This replaces the FAA script's old `pdf_name|volume` format where a single `BASE_URL` was prepended — the new format is fully self-contained since each country has different base URLs.

### Country Module Contract

Each country module implements a `discover()` function:

```python
def discover(cycle_date, work_dir):
    """
    Discovers all available charts for this country's current AIRAC cycle.

    Args:
        cycle_date: datetime.date for the current AIRAC effective date
        work_dir: directory to write output files

    Returns dict:
        {
            "country": "FR",
            "airports": {
                "LFPG": {
                    "code": "LFPG",
                    "icao": "LFPG",
                    "name": "PARIS-CHARLES DE GAULLE",
                    "volume": "FR",
                    "plates": {
                        "approach": [{"name": "ILS RWY 27L", "page": "AD_2_LFPG_IAC_1", "url": "https://...pdf"}],
                        ...
                    }
                },
                ...
            }
        }

    Returns None if credentials are required but not configured.
    Raises AIPUnavailableError if the AIP is unreachable for this cycle.
    """
```

The `url` field in each plate is the source PDF URL — consumed by the orchestrator to build the download list and **not written** to the final `charts.json`. The `page` field becomes the JPG filename (`.pdf` stripped, same as FAA pipeline).

### Category Mapping

Each country module maps local chart type names to the four standard buckets:

| Category  | FAA (US) | France | Spain  | UK   | Generic European |
|-----------|----------|--------|--------|------|------------------|
| approach  | IAP      | IAC    | IAC    | IAC  | IAC, APCH        |
| departure | DP       | SID    | SID    | SID  | SID              |
| star      | STAR     | STAR   | STAR   | STAR | STAR             |
| diagram   | APD      | ADC    | ADC    | ADC  | ADC, GMC         |

### Credentials Handling

Modules requiring authentication (Italy, potentially Germany) check env vars:
- `MACHETE_ENAV_USER` / `MACHETE_ENAV_PASS` (Italy)

If not set, `discover()` returns `None` and the orchestrator logs:
"Skipping Italy -- no credentials configured" and continues with other countries.

### Error Handling

If a country's AIP is unreachable or the AIRAC cycle page doesn't exist yet, the module raises `AIPUnavailableError`. The orchestrator catches it, logs a warning, and continues. One country failing doesn't block the rest.

### AIRAC Cycle Calculation

Shared in `base.py`. All countries use the same 28-day cycle. Reference epoch: 2020-01-02 (a known AIRAC effective date). From that, compute any cycle's effective date.

Note: while all countries follow the same AIRAC calendar, publication timing varies — some AIP providers post new cycle data several days before the effective date, others may lag. Running `--all` near a cycle boundary may result in some countries being skipped (caught by `AIPUnavailableError`). Recommend running a few days after the effective date for best results.

### FAA Module (`faa.py`)

`faa.py` is self-contained: it computes the FAA cycle number from the AIRAC date, downloads the d-TPP metafile XML from `https://aeronav.faa.gov/d-tpp/{cycle}/xml_data/d-tpp_Metafile.xml`, parses it, and returns the standard `discover()` dict. The existing inline Python from `update-faa-charts.sh` is refactored into this module.

## NAS Directory Structure

```
/volume1/web/MacheteCharts/
  charts.json                   # unified index (all countries merged)
  charts/
    NE-1/                       # existing FAA volumes (unchanged)
    SE-3/
    ...
    FR/                         # France
      AD_2_LFPG_IAC_1.jpg
      ...
    ES/                         # Spain
    NL/                         # Netherlands
    AT/                         # Austria
    GB/                         # UK
    SE/                         # Sweden
    NO/                         # Norway
    DE/                         # Germany
    IT/                         # Italy
```

### Merge Strategy

When updating a subset of countries:
1. Download existing `charts.json` from NAS at start
2. Iterate all entries in the existing JSON and remove those whose `volume` field matches any country being updated
3. Insert all new entries from the country fragments
4. Preserve all other entries (so `update-charts.sh france` doesn't wipe US data)
5. Write merged result back to NAS

If two countries share an airport code (unlikely — ICAO codes have country prefixes), the last-written country wins.

## JS Plugin Changes (Cosmetic Only)

Four text changes across two files:

**`MacheteCharts.html`:**
1. Search placeholder: `"Airport ID (e.g. BOS)"` -> `"Airport ID (e.g. BOS, LFPG)"`
2. Empty state heading: `"FAA Terminal Procedures"` -> `"Terminal Procedures"`
3. Empty state region: `"All US airports"` -> `"US & European airports"`

**`MacheteCharts.js`:**
4. The `clearBtn` click handler (line ~68) rebuilds the empty state with hardcoded text — update to match the new strings above.

No logic changes. `normalizeCode()`, search, plate rendering, and image loading all work unchanged.

## Country Research Summary

### Tier 1 -- Predictable URLs, No Auth (Start Here)

| Country     | Provider       | Domain                          | URL Pattern |
|-------------|----------------|---------------------------------|-------------|
| France      | SIA            | sia.aviation-civile.gouv.fr     | AIRAC date + ICAO code in path |
| Spain       | ENAIRE         | aip.enaire.es                   | Stable URLs, no AIRAC date in path |
| Netherlands | LVNL           | eaip.lvnl.nl                    | AIRAC amendment + ICAO + procedure type |
| Austria     | Austro Control | eaip.austrocontrol.at           | YYMMDD date + ICAO + section number |

### Tier 2 -- Requires Index Scraping

| Country | Provider | Domain                    | Challenge |
|---------|----------|---------------------------|-----------|
| Sweden  | LFV      | aro.lfv.se                | Chart subfolder path needs confirmation |
| UK      | NATS     | aurora.nats.co.uk         | Chart PDFs use opaque numeric IDs |
| Norway  | Avinor   | aim-prod.avinor.no        | Numeric IDs + incrementing index number |

### Tier 3 -- Significant Obstacles

| Country | Provider | Domain      | Challenge |
|---------|----------|-------------|-----------|
| Germany | DFS      | aip.dfs.de  | Hex hash IDs change every cycle, full TOC scraping required. High maintenance — may break silently. Consider experimental. |
| Italy   | ENAV     | enav.it     | Free one-time registration, dynamic URLs, auth sessions. Module needs re-auth logic if session token expires mid-download. |

## Rollout Plan

**Phase 1: Refactor FAA pipeline.** Extract Python parsing into `countries/faa.py`, build `update-charts.sh` orchestrator, verify identical output to old script.

**Phase 2: France (Tier 1 pilot).** Build `countries/france.py`, test with subset of airports (LFPG, LFPO, LFMN), verify merged charts.json works in plugin.

**Phase 3: Remaining Tier 1.** Spain, Netherlands, Austria. Each is a new module following the same contract.

**Phase 4: Tier 2 (index scraping).** Sweden, UK, Norway. More fragile, add retry/fallback logic.

**Phase 5: Tier 3 (auth required).** Germany, Italy. Only if credentials configured.

## Testing

No automated test suite. Verification is manual:
- Spot-check download list URLs (do they resolve?)
- Do PDFs download successfully?
- Do JPGs convert correctly?
- Does merged charts.json load in browser with correct airports?
- Do chart images display in the MSFS plugin?
