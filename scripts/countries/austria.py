"""Austria Austro Control eAIP chart discovery module."""

import os
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import quote
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "AT"
EAIP_BASE = "https://eaip.austrocontrol.at/lo/{yymmdd}/"

# Section number prefix → chart category
SECTION_CATEGORY = {
    "1-":  "diagram",   # Aerodrome Chart
    "9-":  "departure", # SID
    "11-": "star",      # STAR
    "13-": "approach",  # IAC
}

# Section number prefix → short label for human-readable name
SECTION_LABEL = {
    "1-":  "ADC",
    "9-":  "SID",
    "11-": "STAR",
    "13-": "IAP",
}


def _fetch(url):
    """Fetch a URL and return the decoded text content."""
    try:
        with urlopen(url) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"Austro Control eAIP unavailable: {url} — {e}")


def _get_airac_yymmdd():
    """Parse the Austro Control landing page to get the active AIRAC YYMMDD string.

    The computed AIRAC date may differ by one day from the URL used by Austro
    Control, so we always parse the landing page rather than computing it.

    Returns:
        str: 6-digit YYMMDD string, e.g. "260320"
    """
    landing_url = "https://eaip.austrocontrol.at/"
    html = _fetch(landing_url)
    # Look for the current-cycle row: <tr class="current">...<a href="./lo/YYMMDD/index.htm">
    m = re.search(r'class=["\']current["\'][^>]*>.*?href=["\'](?:\./)?lo/(\d{6})/index\.htm', html, re.DOTALL | re.IGNORECASE)
    if not m:
        # Fallback: look for any lo/YYMMDD/index.htm in a class=current context
        m = re.search(r'lo/(\d{6})/index\.htm', html)
        if not m:
            raise AIPUnavailableError("Could not determine active AIRAC YYMMDD from Austro Control landing page")
    return m.group(1)


class _AirportListParser(HTMLParser):
    """Parse ad_2.htm to find airports that have chart pages.

    Chart pages are linked as:  href="ad_2_{icao_lower}.htm"
    with link text containing "Karten/Charts".
    """

    def __init__(self):
        super().__init__()
        self.airports = []          # list of ICAO strings (upper-case)
        self._pending_icao = None   # ICAO found in href, awaiting text confirmation
        self._in_link = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            m = re.match(r"ad_2_([a-z]{4})\.htm$", href, re.IGNORECASE)
            if m:
                self._pending_icao = m.group(1).upper()
                self._in_link = True
                self._link_text = []

    def handle_data(self, data):
        if self._in_link:
            self._link_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            text = " ".join(self._link_text).strip()
            # Accept any link to ad_2_XXXX.htm — not all label text says "Karten/Charts"
            # but we want all airports that have a dedicated chart page.
            if self._pending_icao:
                if self._pending_icao not in self.airports:
                    self.airports.append(self._pending_icao)
            self._in_link = False
            self._pending_icao = None
            self._link_text = []


def _get_airport_name(icao, apt_html):
    """Extract a human-readable airport name from an airport chart page.

    The page title or first prominent heading usually contains the name.
    Falls back to the ICAO code itself.
    """
    # Try <title>...</title>
    m = re.search(r"<title>([^<]+)</title>", apt_html, re.IGNORECASE)
    if m:
        title = m.group(1).strip()
        # Remove the ICAO prefix if present, e.g. "LOWW Wien/Schwechat" → "Wien/Schwechat"
        if title.upper().startswith(icao):
            title = title[len(icao):].strip(" -/")
        if title:
            return title

    # Try first <h1> or <h2>
    m = re.search(r"<h[12][^>]*>([^<]+)</h[12]>", apt_html, re.IGNORECASE)
    if m:
        heading = m.group(1).strip()
        if heading.upper().startswith(icao):
            heading = heading[len(icao):].strip(" -/")
        if heading:
            return heading

    return icao


def _classify_section(section):
    """Map a section string (e.g. '13-1-1') to (category, human_name).

    Returns:
        (category, name) tuple, or (None, None) if the section should be skipped.
    """
    for prefix, category in SECTION_CATEGORY.items():
        if section.startswith(prefix):
            label = SECTION_LABEL[prefix]
            name = f"{label} {section}"
            return category, name
    return None, None


def _parse_chart_links(apt_html, icao):
    """Extract chart entries from an airport chart page.

    Each entry is a dict with keys: category, name, page, chart_path
    where chart_path is the href value (relative to the AIRAC base URL),
    e.g. "Charts/LOWW/LO_AD_2_LOWW_13-1-1_en.pdf"

    Heliport pages (AD 3) are ignored.

    Returns:
        list of chart dicts
    """
    # Skip AD 3 heliport pages
    if re.search(r"Charts/AD_3/", apt_html, re.IGNORECASE):
        # Page references heliport charts — skip entirely
        return []

    # Find all href="Charts/..." links
    chart_hrefs = re.findall(r'href=["\']([^"\']*Charts/[^"\']+\.pdf)["\']', apt_html, re.IGNORECASE)

    charts = []
    seen = set()

    for href in chart_hrefs:
        # Skip AD 3 heliport paths
        if re.search(r"Charts/AD_3/", href, re.IGNORECASE):
            continue

        # Normalise: strip leading "./" if present
        chart_path = href.lstrip("./")
        if chart_path in seen:
            continue
        seen.add(chart_path)

        # Extract filename to get section number
        filename = chart_path.split("/")[-1]
        # Pattern: LO_AD_2_{ICAO}_{SECTION}_en.pdf
        m = re.match(r"LO_AD_2_[A-Z]{4}_([^_].+?)_en\.pdf$", filename, re.IGNORECASE)
        if not m:
            continue
        section = m.group(1)

        category, name = _classify_section(section)
        if category is None:
            continue

        page = filename.replace(".pdf", "").replace(".PDF", "")
        charts.append({
            "category": category,
            "name": name,
            "page": page,
            "chart_path": chart_path,
        })

    return charts


def discover(cycle_date, work_dir):
    """Discover all Austrian approach charts for the current AIRAC cycle.

    Args:
        cycle_date: datetime.date — used for logging only; actual YYMMDD is
                    always parsed from the Austro Control landing page.
        work_dir: directory for output files (used by write_outputs)

    Returns:
        Standard discover() dict with country="austria" and airports dict.
    """
    print("  Fetching active AIRAC date from Austro Control landing page...")
    yymmdd = _get_airac_yymmdd()
    print(f"  Active AIRAC YYMMDD: {yymmdd}")

    base_url = EAIP_BASE.format(yymmdd=yymmdd)
    ad2_url = base_url + "ad_2.htm"

    print(f"  Fetching airport list: {ad2_url}")
    ad2_html = _fetch(ad2_url)

    parser = _AirportListParser()
    parser.feed(ad2_html)
    icao_list = parser.airports
    print(f"  Found {len(icao_list)} airports with chart pages")

    airports = {}

    for i, icao in enumerate(icao_list):
        apt_page_url = base_url + f"ad_2_{icao.lower()}.htm"
        try:
            apt_html = _fetch(apt_page_url)
        except AIPUnavailableError:
            print(f"  WARNING: Could not fetch {icao} chart page, skipping")
            continue

        charts = _parse_chart_links(apt_html, icao)
        if not charts:
            continue

        name = _get_airport_name(icao, apt_html)

        plates = {"diagram": [], "approach": [], "departure": [], "star": []}
        for c in charts:
            # URL-encode the path to handle spaces in subdirectory names
            # (e.g. "Charts/SECONDARY_ LOAA/...") — safe chars keep slashes intact
            encoded_path = quote(c["chart_path"], safe="/:@!$&'()*+,;=")
            pdf_url = base_url + encoded_path
            plates[c["category"]].append({
                "name": c["name"],
                "page": c["page"],
                "url": pdf_url,
            })

        airports[icao] = {
            "code": icao,
            "icao": icao,
            "name": name,
            "volume": COUNTRY,
            "plates": plates,
        }

        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(icao_list)} airports...")
            time.sleep(0.5)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "austria", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Austria Austro Control eAIP: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
