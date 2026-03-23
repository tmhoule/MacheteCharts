"""Spain ENAIRE AIP chart discovery module."""

import os
import re
import sys
from html.parser import HTMLParser
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "ES"
AIP_INDEX_URL = "https://aip.enaire.es/aip/aip-en.html"
AIP_BASE_URL = "https://aip.enaire.es/aip/"

CHART_TYPE_MAP = {
    "IAC": "approach",
    "SID": "departure",
    "STAR": "star",
    "ADC": "diagram",
    "GMC": "diagram",
}

# Chart type prefixes to skip entirely
SKIP_TYPES = {
    "AOC", "VAC", "PDC", "PATC", "DEP", "TRAN", "ATCSMAC",
    "ARR", "VPT", "CDEP", "CARR", "CDA", "ARR_DEP",
}


def _fetch(url):
    """Fetch a URL and return the text content."""
    try:
        with urlopen(url) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"Spain ENAIRE AIP unavailable: {url} — {e}")


class _AIPIndexParser(HTMLParser):
    """Parse the ENAIRE AIP index page to extract airports and chart PDF links.

    The page contains rows like:
        <tr onclick="veaseccion( 'LEBL');" ...>
          <td class="id">LEBL</td>
          ...
          <td class="desc">BARCELONA/Josep Tarradellas Barcelona-El Prat</td>

    And chart links like:
        <a href="contenido_AIP/AD/AD2/LEBL/LE_AD_2_LEBL_IAC_1_en.pdf" ...>

    The parser collects airports in encounter order, then chart hrefs grouped
    by the current active airport (determined by the nearest preceding tr onclick).
    """

    def __init__(self):
        super().__init__()
        # Ordered list of (icao, name) tuples
        self.airports = []
        # Map of icao -> list of relative PDF hrefs
        self.chart_hrefs = {}

        self._current_airport = None   # ICAO set by tr onclick
        self._in_id_td = False         # inside <td class="id">
        self._in_desc_td = False       # inside <td class="desc">
        self._pending_icao = None      # ICAO from tr onclick, waiting for desc
        self._pending_name_parts = []
        self._icao_names = {}          # ICAO -> name (first occurrence wins)

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == "tr":
            onclick = attrs_dict.get("onclick", "")
            m = re.search(r"veaseccion\(\s*'([A-Z]{4}(?:_[A-Z]{4})?)'\s*\)", onclick)
            if m:
                raw = m.group(1)
                # For dual-code airports like LEPA_LESJ, use the first code as key
                self._pending_icao = raw.split("_")[0]
                self._pending_name_parts = []
            return

        if tag == "td":
            cls = attrs_dict.get("class", "")
            if cls == "id":
                self._in_id_td = True
            elif cls == "desc" and self._pending_icao is not None:
                self._in_desc_td = True
                self._pending_name_parts = []
            return

        if tag == "a":
            href = attrs_dict.get("href", "")
            if href.endswith(".pdf") and "AD2" in href:
                # Attribute this chart to whichever airport was most recently opened
                if self._current_airport:
                    self.chart_hrefs.setdefault(self._current_airport, []).append(href)

    def handle_data(self, data):
        if self._in_id_td:
            text = data.strip()
            if text and self._pending_icao and text == self._pending_icao:
                # Confirm the td id matches our expected ICAO
                pass
        elif self._in_desc_td:
            self._pending_name_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "td":
            if self._in_id_td:
                self._in_id_td = False
                # When we see the id td close, activate this airport as current
                if self._pending_icao:
                    self._current_airport = self._pending_icao
                    if self._pending_icao not in self._icao_names:
                        # Name not yet collected; keep pending_icao for desc td
                        pass
            elif self._in_desc_td:
                self._in_desc_td = False
                if self._pending_icao:
                    name = "".join(self._pending_name_parts).strip()
                    if self._pending_icao not in self._icao_names:
                        self._icao_names[self._pending_icao] = name
                        self.airports.append((self._pending_icao, name))
                    self._pending_icao = None
                    self._pending_name_parts = []


def _classify_chart(href):
    """Classify a chart href into (category, name, page) or (None, None, None).

    Args:
        href: relative href like
              "contenido_AIP/AD/AD2/LEBL/LE_AD_2_LEBL_IAC_1_en.pdf"

    Returns:
        (category, name, page) tuple, or (None, None, None) if unwanted.
    """
    filename = href.split("/")[-1]
    # Strip .pdf
    base = filename[:-4] if filename.lower().endswith(".pdf") else filename

    # Pattern: LE_AD_2_{DIR}_{TYPE}_{NUM}_en
    # DIR may be a dual-code like LEPA_LESJ
    m = re.match(r"LE_AD_2_([A-Z]{4}(?:_[A-Z]{4})?)_(.+?)(?:_en)?$", base)
    if not m:
        return None, None, None

    rest = m.group(2)  # e.g. "IAC_1" or "ADC_1_1" or "SID_RWY06"

    # Determine chart type prefix (first underscore-delimited token)
    type_token = rest.split("_")[0]

    if type_token in SKIP_TYPES:
        return None, None, None

    category = CHART_TYPE_MAP.get(type_token)
    if category is None:
        return None, None, None

    # Human-readable name: replace underscores with spaces
    name = rest.replace("_", " ")

    # Page name: use the base filename without _en suffix
    # e.g. "LE_AD_2_LEBL_IAC_1"
    page = re.sub(r"_en$", "", base)

    return category, name, page


def _icao_from_href(href):
    """Extract the airport ICAO code from a chart href.

    The DIR component of the path (4th segment of LE_AD_2_{DIR}_...) may be
    a dual-code like LEPA_LESJ; we return the first code.
    """
    filename = href.split("/")[-1]
    base = filename[:-4] if filename.lower().endswith(".pdf") else filename
    m = re.match(r"LE_AD_2_([A-Z]{4}(?:_[A-Z]{4})?)", base)
    if not m:
        return None
    return m.group(1).split("_")[0]


def discover(cycle_date, work_dir):
    """Discover all Spanish approach charts from the ENAIRE AIP index.

    The cycle_date parameter is accepted for interface consistency but is not
    used in URL construction (ENAIRE uses stable, AIRAC-independent URLs).
    """
    print(f"  Fetching ENAIRE AIP index: {AIP_INDEX_URL}")
    html = _fetch(AIP_INDEX_URL)
    print(f"  Downloaded {len(html):,} bytes")

    parser = _AIPIndexParser()
    parser.feed(html)

    print(f"  Found {len(parser.airports)} airports")

    # Build airport dict
    airports = {}
    icao_names = dict(parser.airports)  # ICAO -> name

    # Also collect all chart hrefs from the raw HTML directly, since the
    # parser's attr-based collection may miss some links.  We'll re-scan with
    # regex for completeness and merge.
    all_hrefs = re.findall(
        r'href="(contenido_AIP/AD/AD2/[^"]+\.pdf)"', html, re.IGNORECASE
    )

    # Group hrefs by airport ICAO
    icao_hrefs = {}
    for href in all_hrefs:
        icao = _icao_from_href(href)
        if icao:
            icao_hrefs.setdefault(icao, []).append(href)

    # Also merge any hrefs captured by the attribute parser
    for icao, hrefs in parser.chart_hrefs.items():
        for href in hrefs:
            if href not in icao_hrefs.get(icao, []):
                icao_hrefs.setdefault(icao, []).append(href)

    # Build airport entries
    for icao, name in parser.airports:
        hrefs = icao_hrefs.get(icao, [])
        plates = {"diagram": [], "approach": [], "departure": [], "star": []}

        seen_pages = set()
        for href in hrefs:
            category, chart_name, page = _classify_chart(href)
            if category is None:
                continue
            if page in seen_pages:
                continue
            seen_pages.add(page)
            url = AIP_BASE_URL + href
            plates[category].append({
                "name": chart_name,
                "page": page,
                "url": url,
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

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "spain", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Spain ENAIRE: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
