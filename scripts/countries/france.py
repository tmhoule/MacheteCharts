"""France SIA eAIP chart discovery module."""

import os
import re
import sys
import time
from html.parser import HTMLParser
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "FR"

CHART_TYPE_MAP = {
    "ADC": "diagram",
    "GMC": "diagram",
    "IAC": "approach",
    "SID": "departure",
    "STAR": "star",
}

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
        self.airports = []
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
    base = filename.replace(".pdf", "").replace(".PDF", "")
    m = re.match(r"AD_2_[A-Z]{4}_(.+)", base)
    if not m:
        return None, None
    rest = m.group(1)

    for prefix, category in CHART_TYPE_MAP.items():
        if rest.startswith(prefix):
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
        apt_url = eaip_url + f"FR-AD-2.{icao}-fr-FR.html"
        try:
            apt_html = _fetch(apt_url)
        except AIPUnavailableError:
            print(f"  WARNING: Could not fetch {icao}, skipping")
            continue

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

        has_plates = any(plates[c] for c in plates)
        if has_plates:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": name,
                "volume": COUNTRY,
                "plates": plates,
            }

        # Progress + brief delay to avoid rate limiting
        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(parser.airports)} airports...")
            time.sleep(1)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "france", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"France SIA: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
