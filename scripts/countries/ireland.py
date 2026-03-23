"""AirNav Ireland AIP chart discovery module."""

import os
import re
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, write_outputs, current_airac_date

COUNTRY = "IE"

BASE_URL = "https://www.airnav.ie"
CHART_INFO_URL = (
    BASE_URL
    + "/air-traffic-management/aeronautical-information-management/"
    "aip-package/{airport}-chart-information"
)

AIRPORTS = {
    "dublin": ("EIDW", "Dublin"),
    "cork": ("EICK", "Cork"),
    "shannon": ("EINN", "Shannon"),
    "donegal": ("EIDL", "Donegal"),
    "ireland-west": ("EIKN", "Ireland West Knock"),
    "kerry": ("EIKY", "Kerry"),
    "sligo": ("EISG", "Sligo"),
    "waterford": ("EIWF", "Waterford"),
    "weston": ("EIWT", "Weston"),
}

# 24-N chart number ranges mapped to categories.
# Ranges are inclusive [start, end].
CHART_NUMBER_RANGES = [
    (1, 3, "diagram"),    # Aerodrome chart, parking, GMC
    (4, 9, None),         # Skip: obstacle/terrain
    (10, 21, "departure"), # SID
    (22, 25, "star"),      # STAR
    (26, 999, "approach"), # IAP: RNP, ILS, LOC, VOR, NDB
]

# Keyword-based fallback classification (checked against link text + filename).
KEYWORD_MAP = [
    # Diagrams
    (re.compile(r"\baerodrome chart\b", re.IGNORECASE), "diagram"),
    (re.compile(r"\bparking\b", re.IGNORECASE), "diagram"),
    (re.compile(r"\bGMC\b"), "diagram"),
    # Departures
    (re.compile(r"\bSID\b"), "departure"),
    # STARs
    (re.compile(r"\bSTAR\b"), "star"),
    # Approaches
    (re.compile(r"\b(ILS|RNP|LOC|NDB|VOR|RNAV|GLS)\b"), "approach"),
    (re.compile(r"\bapproach\b", re.IGNORECASE), "approach"),
]


def _fetch(url):
    """Fetch a URL with a browser-like User-Agent and return text content."""
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"AirNav Ireland unavailable: {url} — {e}")


def _classify_by_number(chart_num):
    """Return category for a 24-N chart number, or None to skip."""
    for start, end, category in CHART_NUMBER_RANGES:
        if start <= chart_num <= end:
            return category
    return "approach"  # default anything above 999 to approach


def _classify_chart(filename, link_text=""):
    """Classify a chart into a category.

    Uses the 24-N number from the filename as primary signal, with keyword
    fallback from link text or filename.

    Args:
        filename: e.g. "EI_AD_2_EIDW_24-26_en.pdf"
        link_text: visible text of the anchor element (optional)

    Returns:
        (category, name) tuple, or (None, None) to skip.
    """
    base = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)

    # Try to parse chart number from filename: EI_AD_2_ICAO_24-N_en, 24-N-M_en,
    # or 24-N_en-(2) revision suffixes.
    m = re.search(r"_24-(\d+)(?:-\d+)*(?:_[Ee][Nn])?(?:-\(\d+\))?$", base)
    if m:
        chart_num = int(m.group(1))
        category = _classify_by_number(chart_num)
        if category is None:
            return None, None
        name = base.replace("_", " ")
        return category, name

    # Keyword fallback: check link text then filename
    combined = f"{link_text} {base}"
    for pattern, category in KEYWORD_MAP:
        if pattern.search(combined):
            name = base.replace("_", " ")
            return category, name

    # Default to approach if we can't classify
    name = base.replace("_", " ")
    return "approach", name


def _scrape_airport(airport_slug, icao):
    """Fetch the chart-information page for one airport and extract chart links.

    Args:
        airport_slug: e.g. "dublin"
        icao: e.g. "EIDW"

    Returns:
        List of dicts: [{"name": ..., "page": ..., "url": ..., "category": ...}]
    """
    url = CHART_INFO_URL.format(airport=airport_slug)
    html = _fetch(url)

    # Extract all getattachment links that look like chart PDFs.
    # URLs have a ?lang=en-IE query string after the .pdf extension, so we
    # match up to (but not including) the first '?' or '"' after the path.
    # Pattern groups: (full_path_no_query, uuid, filename_no_query)
    links = re.findall(
        r'href="(/getattachment/([^/]+)/([^"?]+\.pdf))[^"]*"',
        html,
        re.IGNORECASE,
    )

    # Build a map from bare path -> anchor link text for keyword classification.
    anchor_text_map = {}
    for anchor_match in re.finditer(
        r'<a\b[^>]*href="(/getattachment/[^"?]+\.pdf)[^"]*"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        path = anchor_match.group(1)
        raw_text = re.sub(r"<[^>]+>", " ", anchor_match.group(2))
        anchor_text_map[path] = " ".join(raw_text.split())

    charts = []
    seen_pages = set()

    for full_path, uuid, filename in links:
        # Deduplicate by page name
        page = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
        if page in seen_pages:
            continue
        seen_pages.add(page)

        link_text = anchor_text_map.get(full_path, "")
        category, name = _classify_chart(filename, link_text)
        if category is None:
            continue

        charts.append({
            "category": category,
            "name": name,
            "page": page,
            "url": BASE_URL + full_path,
        })

    return charts


def discover(cycle_date, work_dir):
    """Discover all Irish approach charts from AirNav Ireland AIP.

    cycle_date is accepted for interface compatibility but AirNav Ireland
    serves the current cycle automatically — no date needed in the URL.
    """
    print(f"  AirNav Ireland: fetching {len(AIRPORTS)} airports")

    airports = {}

    for i, (slug, (icao, name)) in enumerate(AIRPORTS.items()):
        print(f"  [{i + 1}/{len(AIRPORTS)}] {icao} ({slug})...", end=" ", flush=True)

        try:
            charts = _scrape_airport(slug, icao)
        except AIPUnavailableError as e:
            print(f"WARNING: {e}")
            continue

        plates = {"diagram": [], "approach": [], "departure": [], "star": []}
        for chart in charts:
            plates[chart["category"]].append({
                "name": chart["name"],
                "page": chart["page"],
                "url": chart["url"],
            })

        total = sum(len(v) for v in plates.values())
        print(f"{total} charts")

        if total > 0:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": name,
                "volume": COUNTRY,
                "plates": plates,
            }

        # Brief pause to be polite to the server
        if i < len(AIRPORTS) - 1:
            time.sleep(0.5)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "ireland", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Ireland AirNav: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
