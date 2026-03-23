"""Czech Republic ANS CR eAIP chart discovery module."""

import os
import re
import sys
import time
from html.parser import HTMLParser
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "CZ"

# Base URL for the ANS CR eAIP — always points to the current AIRAC cycle
EAIP_BASE = "https://aim.rlp.cz/eaip/"
EAIP_HTML = EAIP_BASE + "html/eAIP/"

# Chart type suffix → category mapping.
# Keys are matched as a prefix of the filename suffix (part after "a2-{suffix}-").
# Order matters: more-specific prefixes first where needed.
CHART_TYPE_MAP = [
    ("adc",  "diagram"),
    ("pdc",  "diagram"),
    ("ils",  "approach"),
    ("rnp",  "approach"),
    ("vor",  "approach"),
    ("sid",  "departure"),
    ("star", "star"),
]

# Filename suffix prefixes to skip entirely
SKIP_PREFIXES = ("aoc", "patc", "trca", "omnv", "vfrc")

# Known Czech airports — used as fallback if index discovery fails
KNOWN_AIRPORTS = [
    "LKCS", "LKCV", "LKKB", "LKKU", "LKKV",
    "LKMT", "LKNA", "LKPD", "LKPR", "LKTB", "LKVO",
]


def _fetch(url):
    """Fetch a URL and return the decoded text content."""
    try:
        with urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"Czech ANS CR eAIP unavailable: {url} — {e}")


class _ADIndexParser(HTMLParser):
    """Parse the AD 2 index or menu page to find LK airport ICAO codes and names."""

    def __init__(self):
        super().__init__()
        self.airports = []   # list of (icao, name)
        self._in_link = False
        self._current_icao = None
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            # Match links like: LK-AD-2.LKPR-en-GB.html
            m = re.search(r"LK-AD-2\.(LK[A-Z]{2})-en-GB\.html", href)
            if m:
                self._in_link = True
                self._current_icao = m.group(1)
                self._text_parts = []

    def handle_data(self, data):
        if self._in_link:
            stripped = data.strip()
            if stripped:
                self._text_parts.append(stripped)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            raw = " ".join(self._text_parts)
            icao = self._current_icao
            # Strip leading ICAO code from name if present
            name = raw
            if name.upper().startswith(icao):
                name = name[len(icao):].strip(" -–")
            if not name:
                name = icao
            # Deduplicate: only add if not already present
            if not any(c == icao for c, _ in self.airports):
                self.airports.append((icao, name))
            self._in_link = False


def _discover_airports():
    """Fetch the AD 1.3 index (or main index) to discover all LK airport ICAO codes.

    Falls back to the known airport list if the page is unreachable or yields
    fewer results than expected.

    Returns:
        list of (icao, name) tuples
    """
    candidates = [
        EAIP_HTML + "LK-AD-1.3-en-GB.html",
        EAIP_BASE + "html/index-en-GB.html",
    ]

    for url in candidates:
        try:
            html = _fetch(url)
        except AIPUnavailableError:
            continue
        parser = _ADIndexParser()
        parser.feed(html)
        if len(parser.airports) >= len(KNOWN_AIRPORTS):
            print(f"  Discovered {len(parser.airports)} airports from {url}")
            return parser.airports

    # Fallback to known list with ICAO code as name
    print(f"  WARNING: Index discovery failed, falling back to {len(KNOWN_AIRPORTS)} known airports")
    return [(icao, icao) for icao in KNOWN_AIRPORTS]


def _classify_chart(suffix):
    """Classify a chart filename suffix into (category, name).

    Args:
        suffix: the part of the PDF stem after "a2-{airport}-", e.g. "ils24", "star24n"

    Returns:
        (category, name) tuple, or (None, None) if the chart should be skipped.
    """
    suffix_lower = suffix.lower()

    for skip in SKIP_PREFIXES:
        if suffix_lower.startswith(skip):
            return None, None

    for prefix, category in CHART_TYPE_MAP:
        if suffix_lower.startswith(prefix):
            # Human-readable name: upper-case the suffix, spaces replaced by hyphens
            name = suffix.upper()
            return category, name

    return None, None


def _parse_airport_charts(icao, html):
    """Extract chart plates from an airport HTML page.

    Args:
        icao: ICAO code, e.g. "LKPR"
        html: HTML text of the airport's eAIP page

    Returns:
        dict with keys "diagram", "approach", "departure", "star", each a list of plate dicts
    """
    airport_suffix = icao[2:].lower()  # e.g. "pr" from "LKPR"

    plates = {"diagram": [], "approach": [], "departure": [], "star": []}

    # Match relative hrefs pointing into the graphics directory.
    # Typical href: "../../graphics/a2-pr-ils24.pdf"
    # Also handle paths like "../graphics/..." or just "graphics/..."
    pattern = re.compile(
        r'href="[^"]*graphics/(a2-' + re.escape(airport_suffix) + r'-([^"]+?)\.pdf)"',
        re.IGNORECASE,
    )

    seen = set()
    for m in pattern.finditer(html):
        pdf_filename = m.group(1)   # e.g. "a2-pr-ils24.pdf" (without leading path)
        chart_suffix = m.group(2)   # e.g. "ils24"

        if pdf_filename in seen:
            continue
        seen.add(pdf_filename)

        category, name = _classify_chart(chart_suffix)
        if category is None:
            continue

        stem = f"a2-{airport_suffix}-{chart_suffix}"
        pdf_url = EAIP_BASE + f"graphics/{pdf_filename}"

        plates[category].append({
            "name": name,
            "page": stem,
            "url": pdf_url,
        })

    return plates


def discover(cycle_date, work_dir):
    """Discover all Czech Republic approach charts from ANS CR eAIP.

    The eAIP always serves the current AIRAC cycle so cycle_date is accepted
    for interface compatibility but does not affect the URL.
    """
    print(f"  eAIP URL: {EAIP_HTML}")
    print(f"  Discovering airports...")

    airport_list = _discover_airports()
    print(f"  Processing {len(airport_list)} airports...")

    airports = {}

    for i, (icao, name) in enumerate(airport_list):
        apt_url = EAIP_HTML + f"LK-AD-2.{icao}-en-GB.html"
        try:
            apt_html = _fetch(apt_url)
        except AIPUnavailableError:
            print(f"  WARNING: Could not fetch {icao} ({apt_url}), skipping")
            continue

        plates = _parse_airport_charts(icao, apt_html)

        has_plates = any(plates[c] for c in plates)
        if has_plates:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": name,
                "volume": COUNTRY,
                "plates": plates,
            }

        if (i + 1) % 5 == 0:
            print(f"  Processed {i + 1}/{len(airport_list)} airports...")
            time.sleep(0.5)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "czech", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Czech ANS CR eAIP: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
