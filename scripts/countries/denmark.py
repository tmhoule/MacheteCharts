"""Denmark Naviair AIP chart discovery module.

Covers Denmark (EK prefix), Faroe Islands (EK prefix), and Greenland (BG prefix).
Uses the Naviair REST API — no authentication required.
"""

import json
import os
import re
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "denmark"
VOLUME = "DK"
BASE_URL = "https://aim.naviair.dk"
API_URL = BASE_URL + "/umbraco/api/naviairapi/getnodesforparent?parentId={}"

# Node IDs for the "AD 2 AERODROMES" section of each AIP
# These are stable structural nodes, not per-cycle.
AD2_NODES = {
    "denmark": 304,
    "faroe": 3791,
    "greenland": 927,
}

# Patterns that classify a chart as approach (case-insensitive key fragments)
APPROACH_FRAGMENTS = [
    "_ILS_",
    "_LOC_",
    "_RNP_",
    "_NDB_",
    "_VOR_",
    "_GNSS_",
]

# Patterns that classify as departure
DEPARTURE_FRAGMENTS = [
    "_SID_",
]

# Patterns that classify as STAR
STAR_FRAGMENTS = [
    "_STAR_",
]

# Patterns that classify as aerodrome diagram
DIAGRAM_FRAGMENTS = [
    "_ADC_",
    "_GMC_",
]

# Patterns whose presence means we skip the chart entirely
SKIP_FRAGMENTS = [
    "_VAC_",
    "_HELC_",
    "_AOC_",
    "_PATC_",
    "_ATCSMAC_",
    "_APDC_",
    "_VFR_",
    "_LDC_",
    "_GLIDER_",
    "_FIZ_",
]


def _fetch_json(node_id):
    """Fetch the API for a given parentId and return the parsed JSON list."""
    url = API_URL.format(node_id)
    try:
        with urlopen(url) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return json.loads(data)
    except URLError as e:
        raise AIPUnavailableError(f"Naviair API unavailable: {url} — {e}")
    except json.JSONDecodeError as e:
        raise AIPUnavailableError(f"Naviair API returned invalid JSON: {url} — {e}")


def _contains_any(text, fragments):
    """Return True if text (uppercased) contains any of the fragment strings."""
    upper = text.upper()
    return any(f.upper() in upper for f in fragments)


def _classify_chart(filename):
    """Classify a chart filename into a category.

    Args:
        filename: PDF filename from the API name field,
                  e.g. "EK_AD_2_EKBI_ILS_or_LOC_Z_RWY_09_1_CAT_I_II_III_en.pdf"

    Returns:
        category string ("approach", "departure", "star", "diagram"),
        or None if the chart should be skipped.
    """
    # Skip non-PDF entries
    if not filename.lower().endswith(".pdf"):
        return None

    # Strip _en.pdf / _da.pdf suffix for matching but keep full name for page
    stem = filename
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]  # strip .pdf

    # Skip unwanted chart types first
    if _contains_any(stem, SKIP_FRAGMENTS):
        return None

    # Classify by priority: departure before approach (SID_RNP should be departure)
    if _contains_any(stem, DEPARTURE_FRAGMENTS):
        return "departure"
    if _contains_any(stem, STAR_FRAGMENTS):
        return "star"
    if _contains_any(stem, DIAGRAM_FRAGMENTS):
        return "diagram"
    if _contains_any(stem, APPROACH_FRAGMENTS):
        return "approach"

    # Unknown / text-only files (e.g. EK_AD_2_EKBI_en.pdf) — skip
    return None


def _extract_icao_and_name(node_name, region):
    """Extract ICAO code and airport name from a node name string.

    Denmark / Faroe format: "Billund - EKBI"  or  "Vagar - EKVG"
    Greenland format: "Ilulissat (BGJN)"

    Args:
        node_name: the 'name' field from the API
        region: "greenland" or other

    Returns:
        (icao, name) tuple, or (None, None) if not parseable.
    """
    if region == "greenland":
        # "Ilulissat (BGJN)" or "Pituffik (BGTL) (MIL)"
        m = re.search(r"\(([A-Z]{4})\)", node_name)
        if m:
            icao = m.group(1)
            # Name is everything before the first parenthesis, stripped
            name = node_name[:node_name.index("(")].strip().rstrip("-").strip()
            return icao, name
    else:
        # "Billund - EKBI" or "Bornholm Ronne - EKRN"
        m = re.search(r"-\s*([A-Z]{4})\s*$", node_name)
        if m:
            icao = m.group(1)
            name = node_name[:node_name.rfind("-")].strip()
            return icao, name

    return None, None


def _process_airport_node(node, region):
    """Fetch chart nodes for an airport and build the plates dict.

    Args:
        node: API node dict for the airport
        region: "denmark", "faroe", or "greenland"

    Returns:
        (icao, airport_dict) tuple, or (None, None) if no relevant charts.
    """
    icao, name = _extract_icao_and_name(node["name"], region)
    if not icao:
        return None, None

    chart_nodes = _fetch_json(node["id"])

    plates = {"diagram": [], "approach": [], "departure": [], "star": []}

    for chart in chart_nodes:
        filename = chart.get("name", "")
        href = chart.get("href", "")
        if not href or not filename.lower().endswith(".pdf"):
            continue

        category = _classify_chart(filename)
        if category is None:
            continue

        page = filename
        if page.lower().endswith(".pdf"):
            page = page[:-4]

        # Use the API 'title' as the human-readable chart name if available,
        # otherwise fall back to the filename stem.
        title = chart.get("title") or ""
        # Strip leading "NN. " numbering from title
        title = re.sub(r"^\d+\.\s*", "", title).strip()
        if not title:
            title = page.replace("_", " ")

        url = BASE_URL + href

        plates[category].append({
            "name": title,
            "page": page,
            "url": url,
        })

    has_plates = any(plates[cat] for cat in plates)
    if not has_plates:
        return None, None

    airport_dict = {
        "code": icao,
        "icao": icao,
        "name": name,
        "volume": VOLUME,
        "plates": plates,
    }
    return icao, airport_dict


def discover(cycle_date, work_dir):
    """Discover all Naviair AIP charts for the given AIRAC cycle.

    Covers Denmark, Faroe Islands, and Greenland.
    The cycle_date parameter is accepted for interface compatibility but the
    Naviair API always returns the current live data.
    """
    airports = {}

    for region, ad2_node_id in AD2_NODES.items():
        print(f"  Fetching {region} airport list (AD2 node {ad2_node_id})...")
        airport_nodes = _fetch_json(ad2_node_id)
        print(f"  Found {len(airport_nodes)} airports in {region}")

        for i, apt_node in enumerate(airport_nodes):
            if not apt_node.get("hasChildren"):
                continue

            icao, apt_dict = _process_airport_node(apt_node, region)
            if icao and apt_dict:
                airports[icao] = apt_dict

            # Brief delay every 10 airports to be polite
            if (i + 1) % 10 == 0:
                time.sleep(0.5)

        print(f"  {region}: done")

    print(f"  Total: {len(airports)} airports with charts")
    return {"country": COUNTRY, "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Denmark Naviair AIP: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
