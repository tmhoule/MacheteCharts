"""Finland ANS Finland / Fintraffic eAIP chart discovery module."""

import os
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import quote
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, write_outputs, current_airac_date

COUNTRY = "FI"

# Base URL always points to the current AIRAC cycle.
BASE_URL = "https://www.ais.fi/eaip/currently_effective/"
EAIP_URL = BASE_URL + "eAIP/"

# Suffixes to skip (not useful for flight operations in the sim).
_SKIP_SUFFIXES = frozenset([
    "AOC", "PATC", "ATCSMAC", "ARC", "VAC", "MARK", "APDC",
    "FAS_DB", "WPT_LIST", "OMNIDEP", "COPTER",
])


def _fetch(url):
    """Fetch a URL and return decoded text content."""
    try:
        with urlopen(url) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"Finland ANS eAIP unavailable: {url} — {e}")


class _MenuParser(HTMLParser):
    """Parse eAIP/menu.html to extract ICAO codes and city names.

    Airport HTML filenames follow the pattern:
        EF-AD 2 {ICAO} - {CITY} {N}-fi-FI.html

    City names are in uppercase and may contain Finnish characters (Ä, Ö).
    The same names are used for the en-GB pages.
    """

    def __init__(self):
        super().__init__()
        self._airports = {}  # icao -> city (first occurrence wins)

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        # Match: EF-AD 2 EFXX - CITY NAME N-fi-FI.html
        m = re.match(r"EF-AD 2 (EF[A-Z]{2}) - (.+?) \d+-fi-FI\.html", href)
        if m:
            icao = m.group(1)
            city = m.group(2).strip()
            if icao not in self._airports:
                self._airports[icao] = city

    @property
    def airports(self):
        """Return list of (icao, city) tuples sorted by ICAO code."""
        return sorted(self._airports.items())


def _apt_page_url(icao, city):
    """Build the URL for airport page 1 (en-GB), which lists all chart PDFs.

    City names from the menu are already uppercase (e.g. 'HELSINKI-VANTAA',
    'JYVÄSKYLÄ').  The filename must be URL-encoded to handle non-ASCII chars.
    """
    filename = f"EF-AD 2 {icao} - {city} 1-en-GB.html"
    return EAIP_URL + quote(filename, safe="")


def _classify_suffix(suffix):
    """Classify a chart suffix into a category.

    Args:
        suffix: the part after EF_AD_2_{ICAO}_ in the PDF filename,
                e.g. "ADC", "04L_ILS", "22R_SIDR2", "04L_STAR".

    Returns:
        (category, human_name) or (None, None) to skip.
    """
    # Diagrams
    if suffix == "ADC":
        return "diagram", "ADC"
    if suffix == "AGMC" or suffix.startswith("AGMC_"):
        name = suffix.replace("_", " ")
        return "diagram", name

    # Skip unwanted chart types.  Check each token of the suffix.
    # A suffix like "04R_COPTER_ILS" should be skipped due to "COPTER".
    tokens = suffix.split("_")
    for token in tokens:
        if token in _SKIP_SUFFIXES:
            return None, None

    # ILS variants: ends with ILS, ILSY, ILSZ, ILSX
    if re.search(r"_ILS[XYZ]?$", suffix):
        name = suffix.replace("_", " ")
        return "approach", name

    # Other instrument approaches
    if suffix.endswith("_RNP") or suffix.endswith("_VOR") or suffix.endswith("_INA"):
        name = suffix.replace("_", " ")
        return "approach", name

    # Departures: SIDR, SIDRP, SIDR2
    if re.search(r"_SIDR(?:P|2)?$", suffix):
        name = suffix.replace("_", " ")
        return "departure", name

    # STARs
    if suffix.endswith("_STAR") or suffix.endswith("_STAR2"):
        name = suffix.replace("_", " ")
        return "star", name

    return None, None


def _extract_charts(icao, html):
    """Extract and classify chart PDFs from an airport HTML page.

    Returns a plates dict: {"diagram": [...], "approach": [...], ...}
    Each plate entry has keys: name, page, url.
    """
    plates = {"diagram": [], "approach": [], "departure": [], "star": []}

    # All PDF hrefs are relative paths like:
    #   ../documents/Root_WePub/ANSFI/Charts/AD/{ICAO}/EF_AD_2_{ICAO}_{SUFFIX}.pdf
    pattern = re.compile(
        rf'\.\./documents/Root_WePub/ANSFI/Charts/AD/{icao}/'
        rf'(EF_AD_2_{icao}_([^"\']+?)\.pdf)',
        re.IGNORECASE,
    )

    seen = set()
    for m in pattern.finditer(html):
        filename = m.group(1)
        suffix = m.group(2)

        if filename in seen:
            continue
        seen.add(filename)

        category, name = _classify_suffix(suffix)
        if category is None:
            continue

        page = filename.replace(".pdf", "").replace(".PDF", "")
        url = BASE_URL + f"documents/Root_WePub/ANSFI/Charts/AD/{icao}/{filename}"
        plates[category].append({"name": name, "page": page, "url": url})

    return plates


def discover(cycle_date, work_dir):
    """Discover all Finnish approach charts for the current AIRAC cycle.

    The Finland eAIP uses a stable 'currently_effective' URL that always
    resolves to the live AIRAC cycle, so cycle_date is not used to construct
    URLs but is accepted for interface compatibility.
    """
    menu_url = EAIP_URL + "menu.html"

    print(f"  Base URL: {BASE_URL}")
    print(f"  Fetching menu: {menu_url}")
    menu_html = _fetch(menu_url)

    parser = _MenuParser()
    parser.feed(menu_html)
    apt_list = parser.airports
    print(f"  Found {len(apt_list)} airports in menu")

    airports = {}

    for i, (icao, city) in enumerate(apt_list):
        apt_url = _apt_page_url(icao, city)
        try:
            apt_html = _fetch(apt_url)
        except AIPUnavailableError:
            print(f"  WARNING: Could not fetch {icao} ({city}), skipping")
            continue

        plates = _extract_charts(icao, apt_html)
        has_plates = any(plates[c] for c in plates)

        if has_plates:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": city.title(),
                "volume": COUNTRY,
                "plates": plates,
            }

        # Progress + brief delay to be polite to the server
        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(apt_list)} airports...")
            time.sleep(0.5)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "finland", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Finland ANS eAIP: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
