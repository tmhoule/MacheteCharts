"""Poland PANSA eAIP chart discovery module."""

import os
import re
import sys
import time
from html.parser import HTMLParser
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIRAC_EPOCH, AIRAC_CYCLE_DAYS, AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "PL"

# Section number → chart category mapping
SECTION_CATEGORY = {
    "08": "departure",   # SID
    "10": "approach",    # IAC (instrument approach)
    "12": "star",        # STAR
}

# Known Polish airports: ICAO code → name
KNOWN_AIRPORTS = {
    "EPWA": "Warsaw Chopin",
    "EPKK": "Krakow John Paul II",
    "EPGD": "Gdansk Lech Walesa",
    "EPPO": "Poznan Lawica",
    "EPWR": "Wroclaw Copernicus",
    "EPKT": "Katowice Pyrzowice",
    "EPSC": "Szczecin Goleniow",
    "EPBY": "Bydgoszcz Ignacy Jan Paderewski",
    "EPLB": "Lublin",
    "EPZG": "Zielona Gora Babimost",
    "EPLL": "Lodz Wladyslaw Reymont",
    "EPRZ": "Rzeszow Jasionka",
    "EPRA": "Radom",
}


def _amendment_number(cycle_date):
    """Compute the AIRAC amendment number within the year (01-13).

    The numbering restarts each year: cycle 1 of a year = amendment 01.
    """
    jan1 = cycle_date.replace(month=1, day=1)
    days_to_jan1 = (jan1 - AIRAC_EPOCH).days
    first_cycle = days_to_jan1 // AIRAC_CYCLE_DAYS
    if (jan1 - AIRAC_EPOCH).days % AIRAC_CYCLE_DAYS != 0:
        first_cycle += 1
    total_cycle = (cycle_date - AIRAC_EPOCH).days // AIRAC_CYCLE_DAYS
    return total_cycle - first_cycle + 1


def _build_base_url(cycle_date):
    """Build the PANSA eAIP base URL for the given AIRAC cycle date.

    URL pattern:
        https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%20{AA}-{YY}_{YYYY}_{MM}_{DD}/
    """
    aa = _amendment_number(cycle_date)
    yy = cycle_date.year % 100
    yyyy = cycle_date.year
    mm = cycle_date.month
    dd = cycle_date.day
    amdt = f"AIRAC%20AMDT%20{aa:02d}-{yy:02d}_{yyyy}_{mm:02d}_{dd:02d}"
    return f"https://docs.pansa.pl/ais/eaipifr/{amdt}/"


def _fetch(url, timeout=20):
    """Fetch a URL and return the text content."""
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; MacheteCharts/1.0)"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"PANSA eAIP unavailable: {url} — {e}")


def _head_ok(url, timeout=15):
    """Return True if a HEAD request to url returns HTTP 200."""
    req = Request(url, method="HEAD", headers={
        "User-Agent": "Mozilla/5.0 (compatible; MacheteCharts/1.0)"
    })
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


class _MenuParser(HTMLParser):
    """Parse the PANSA eAIP menu page to extract airport ICAO codes and names."""

    def __init__(self):
        super().__init__()
        self.airports = []
        self._in_airport_link = False
        self._current_icao = None
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            # Look for airport section links, e.g. EP-AD-2.EPWA-en-GB.html
            m = re.search(r"EP-AD-2\.([A-Z]{4})-en-GB\.html", href)
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
            if icao:
                self.airports.append((icao, name or icao))
            self._in_airport_link = False


def _discover_airports_from_menu(base_url):
    """Fetch the eAIP menu and extract airport ICAO codes and names.

    Returns list of (icao, name) tuples, or empty list if menu unavailable.
    """
    menu_url = base_url + "eAIP/EP-menu-en-GB.html"
    try:
        html = _fetch(menu_url)
    except AIPUnavailableError:
        return []

    parser = _MenuParser()
    parser.feed(html)

    # Deduplicate while preserving order
    seen = set()
    result = []
    for icao, name in parser.airports:
        if icao not in seen:
            seen.add(icao)
            result.append((icao, name))
    return result


def _fetch_airport_charts(base_url, icao):
    """Fetch the airport HTML page and extract chart PDF links.

    Chart PDF URL pattern:
        documents/Root_WePub/AIP%20IFR/AD/{ICAO}/{SS}/AD_2_{ICAO}_{SS}-{N}.pdf

    Returns list of (section, page_number, pdf_url) tuples.
    """
    apt_url = base_url + f"eAIP/EP-AD-2.{icao}-en-GB.html"
    try:
        html = _fetch(apt_url)
    except AIPUnavailableError:
        return []

    # Match PDF links with the known section/page pattern
    charts = []
    # Pattern: AD_2_{ICAO}_{SS}-{N}.pdf (section SS, page N)
    pattern = re.compile(
        rf'href="[^"]*?documents/Root_WePub/AIP%20IFR/AD/{re.escape(icao)}'
        rf'/(\d{{2}})/AD_2_{re.escape(icao)}_(\d{{2}})-(\d+)\.pdf"',
        re.IGNORECASE,
    )
    for m in pattern.finditer(html):
        section = m.group(1)
        sec_check = m.group(2)
        page_num = m.group(3)
        if section != sec_check:
            # Malformed link — skip
            continue
        if section not in SECTION_CATEGORY:
            continue
        # Reconstruct the full PDF URL from the href
        pdf_rel = (
            f"documents/Root_WePub/AIP%20IFR/AD/{icao}"
            f"/{section}/AD_2_{icao}_{section}-{page_num}.pdf"
        )
        pdf_url = base_url + pdf_rel
        charts.append((section, page_num, pdf_url))

    # Also try a simpler pattern in case the href uses a relative path
    if not charts:
        pattern2 = re.compile(
            rf'href="([^"]*?AD_2_{re.escape(icao)}_(\d{{2}})-(\d+)\.pdf)"',
            re.IGNORECASE,
        )
        for m in pattern2.finditer(html):
            href = m.group(1)
            section = m.group(2)
            page_num = m.group(3)
            if section not in SECTION_CATEGORY:
                continue
            # Build absolute URL
            if href.startswith("http"):
                pdf_url = href
            else:
                # Relative to the base_url
                pdf_url = base_url + href.lstrip("./")
            charts.append((section, page_num, pdf_url))

    return charts


def _probe_airport_charts(base_url, icao):
    """Probe candidate PDF URLs for an airport using HEAD requests.

    Fallback when HTML parsing yields no results.
    Probes sections 08, 10, 12 with pages 1–8.
    """
    charts = []
    for section in ("08", "10", "12"):
        for page_num in range(1, 9):
            pdf_url = (
                f"{base_url}documents/Root_WePub/AIP%20IFR/AD/{icao}"
                f"/{section}/AD_2_{icao}_{section}-{page_num}.pdf"
            )
            if _head_ok(pdf_url):
                charts.append((section, str(page_num), pdf_url))
            else:
                # Stop probing pages once we get a miss, to avoid exhausting all
                # page slots on airports that have fewer charts
                if page_num > 1:
                    break
    return charts


def discover(cycle_date, work_dir):
    """Discover all Polish approach charts for the given AIRAC cycle."""
    base_url = _build_base_url(cycle_date)
    print(f"  Base URL: {base_url}")

    # Try menu-based airport discovery
    print("  Fetching airport list from menu...")
    menu_airports = _discover_airports_from_menu(base_url)

    if menu_airports:
        print(f"  Found {len(menu_airports)} airports in menu")
        airport_list = menu_airports
        # Fill in known names where the menu name is just the ICAO code
        airport_map = {icao: name for icao, name in airport_list}
        for icao, known_name in KNOWN_AIRPORTS.items():
            if icao in airport_map and airport_map[icao] == icao:
                airport_map[icao] = known_name
        airport_list = list(airport_map.items())
    else:
        print("  Menu unavailable, falling back to known airports list")
        airport_list = list(KNOWN_AIRPORTS.items())

    # Verify base URL is reachable (probe a known EPWA approach chart)
    test_url = (
        f"{base_url}documents/Root_WePub/AIP%20IFR/AD/EPWA/10/AD_2_EPWA_10-1.pdf"
    )
    print(f"  Verifying base URL with {test_url}")
    if not _head_ok(test_url):
        raise AIPUnavailableError(f"PANSA eAIP unreachable or cycle not published: {test_url}")

    airports = {}
    total = len(airport_list)

    for idx, (icao, apt_name) in enumerate(airport_list, 1):
        print(f"  [{idx}/{total}] {icao} {apt_name}...", end="", flush=True)

        charts = _fetch_airport_charts(base_url, icao)

        if not charts:
            # Fall back to probing
            charts = _probe_airport_charts(base_url, icao)

        plates = {"diagram": [], "approach": [], "departure": [], "star": []}

        # Section-level page counter for human-readable names
        section_page_counts = {}

        for section, page_num, pdf_url in charts:
            category = SECTION_CATEGORY.get(section)
            if category is None:
                continue

            # Derive page identifier (unique within the volume)
            page = f"AD_2_{icao}_{section}-{page_num}"

            # Human-readable name based on section type and page number
            type_label = {"08": "SID", "10": "IAC", "12": "STAR"}.get(section, section)
            name = f"{type_label} {section}-{page_num}"

            plates[category].append({
                "name": name,
                "page": page,
                "url": pdf_url,
            })

        total_charts = sum(len(v) for v in plates.values())
        print(f" {total_charts} charts")

        if total_charts > 0:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": apt_name,
                "volume": COUNTRY,
                "plates": plates,
            }

        # Brief delay every 10 airports to be polite
        if idx % 10 == 0:
            time.sleep(1)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "poland", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Poland PANSA: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
