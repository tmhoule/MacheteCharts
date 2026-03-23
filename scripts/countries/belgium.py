"""Belgium skeyes eAIP chart discovery module.

The skeyes eAIP requires a browser-like User-Agent header; bare urllib/curl
User-Agents receive a 403 response.  All fetches use the browser UA defined
in BROWSER_UA below.

Base URL structure:
  https://ops.skeyes.be/html/belgocontrol_static/eaip/eAIP_Main/
    html/eAIP/EB-menu-en-GB.html          — airport index/menu
    html/eAIP/EB-AD-2.{ICAO}-en-GB.html  — per-airport page
    graphics/eAIP/{ICAO}_{TYPE}{NN}_v{VV}.pdf  — chart PDF

The _v{VV} version suffix in chart filenames changes with each AIRAC
amendment, so we always parse the airport HTML page to discover current
filenames rather than constructing them from templates.
"""

import os
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "BE"

EAIP_BASE = "https://ops.skeyes.be/html/belgocontrol_static/eaip/eAIP_Main/"

# Browser-like User-Agent — required to avoid 403 from skeyes server
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Chart type code → category
CHART_TYPE_MAP = {
    "IAC":  "approach",
    "SID":  "departure",
    "STAR": "star",
    "ADC":  "diagram",
    "GMC":  "diagram",
}

# Chart type codes to skip entirely
SKIP_TYPES = {"AOC", "APDC", "PATC", "ATCSMAC", "VAC"}


def _fetch(url):
    """Fetch a URL with a browser User-Agent and return the decoded text.

    Raises AIPUnavailableError on network or HTTP errors.
    """
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"Belgium skeyes eAIP unavailable: {url} — {e}")


def _head_ok(url):
    """Return True if a HEAD request to url returns HTTP 200."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


class _MenuParser(HTMLParser):
    """Parse the skeyes eAIP menu page to extract EB** airport ICAO codes.

    Looks for links of the form:
      href="EB-AD-2.EBXX-en-GB.html#AD-2.eAIP."
    and collects the linked text as the airport name.
    """

    def __init__(self):
        super().__init__()
        self.airports = []          # list of (icao, name)
        self._in_link = False
        self._current_icao = None
        self._text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            # Match airport-specific page links: EB-AD-2.EBXX-en-GB.html
            m = re.search(r"EB-AD-2\.(EB[A-Z]{2})-en-GB\.html", href)
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
            icao = self._current_icao
            raw_name = " ".join(self._text_parts)
            # Strip leading ICAO code from name if present (e.g. "EBBR Brussels")
            if raw_name.upper().startswith(icao):
                raw_name = raw_name[len(icao):].strip(" -/")
            name = raw_name or icao
            # Deduplicate — the menu may link the same airport multiple times
            if not any(a[0] == icao for a in self.airports):
                self.airports.append((icao, name))
            self._in_link = False
            self._current_icao = None
            self._text_parts = []


def _classify_chart(icao, filename):
    """Classify a chart filename into (category, name, page).

    Expected filename patterns:
      {ICAO}_{TYPE}{NN}_v{VV}.pdf     e.g. EBBR_IAC01_v3.pdf
      {ICAO}_{TYPE}{NN}_{SUFFIX}_v{VV}.pdf

    The TYPE is the chart type code (IAC, SID, STAR, ADC, GMC, …).

    Returns:
        (category, name, page) tuple, or (None, None, None) to skip.
    """
    base = filename.replace(".pdf", "").replace(".PDF", "")
    prefix = icao + "_"
    if not base.startswith(prefix):
        return None, None, None

    rest = base[len(prefix):]

    # Extract the leading TYPE token (uppercase letters only)
    m = re.match(r"([A-Z]+)(.*)", rest)
    if not m:
        return None, None, None
    chart_type = m.group(1)

    if chart_type in SKIP_TYPES:
        return None, None, None

    category = CHART_TYPE_MAP.get(chart_type)
    if category is None:
        return None, None, None

    # Human-readable name: replace underscores with spaces, strip version suffix
    name = rest.replace("_", " ")
    # Remove trailing " v{N}" version marker for display
    name = re.sub(r"\s+v\d+$", "", name).strip()
    name = f"{chart_type} {name}" if not name.startswith(chart_type) else name

    page = base
    return category, name, page


def discover(cycle_date, work_dir):
    """Discover all Belgian approach charts for the given AIRAC cycle.

    The skeyes eAIP uses a fixed URL (eAIP_Main = current AIRAC) so
    cycle_date is used for logging only — the live data is always current.

    Args:
        cycle_date: datetime.date (used for logging)
        work_dir: directory for output files

    Returns:
        Standard discover() dict with country="belgium" and airports dict.
    """
    eaip_html_base = EAIP_BASE + "html/eAIP/"
    graphics_base = EAIP_BASE + "graphics/eAIP/"
    menu_url = eaip_html_base + "EB-menu-en-GB.html"

    print(f"  Base URL: {EAIP_BASE}")
    print(f"  Fetching menu: {menu_url}")
    try:
        menu_html = _fetch(menu_url)
    except AIPUnavailableError as e:
        raise AIPUnavailableError(f"Could not fetch skeyes menu: {e}")

    parser = _MenuParser()
    parser.feed(menu_html)
    found_airports = parser.airports

    # If menu parsing yielded no results (layout may differ), fall back to
    # scanning the HTML for any EB** ICAO codes referenced in href attributes.
    if not found_airports:
        icao_codes = sorted(set(re.findall(r"EB-AD-2\.(EB[A-Z]{2})-en-GB", menu_html)))
        found_airports = [(code, code) for code in icao_codes]

    print(f"  Found {len(found_airports)} airports in menu")

    airports = {}

    for idx, (icao, apt_name) in enumerate(found_airports, 1):
        apt_url = eaip_html_base + f"EB-AD-2.{icao}-en-GB.html"
        print(f"  [{idx}/{len(found_airports)}] {icao} ({apt_name})...", end="", flush=True)

        try:
            apt_html = _fetch(apt_url)
        except AIPUnavailableError:
            print(f" WARNING: could not fetch, skipping")
            continue

        # Extract airport name from page title if we only have the ICAO code
        if apt_name == icao:
            m = re.search(r"<title>([^<]+)</title>", apt_html, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                if title.upper().startswith(icao):
                    title = title[len(icao):].strip(" -/")
                if title:
                    apt_name = title

        # Find all PDF hrefs matching the Belgium chart pattern:
        # graphics/eAIP/{ICAO}_*.pdf
        chart_hrefs = re.findall(
            rf'href="(?:[^"]*/)?(graphics/eAIP/{icao}_[^"]+\.pdf)"',
            apt_html,
            re.IGNORECASE,
        )
        # Also catch relative references without the leading path
        chart_hrefs += re.findall(
            rf'href="({icao}_[^"]+\.pdf)"',
            apt_html,
            re.IGNORECASE,
        )

        # Deduplicate while preserving order
        seen_hrefs = set()
        unique_hrefs = []
        for href in chart_hrefs:
            if href not in seen_hrefs:
                seen_hrefs.add(href)
                unique_hrefs.append(href)

        plates = {"diagram": [], "approach": [], "departure": [], "star": []}
        found_count = 0

        for href in unique_hrefs:
            # Normalise to just the filename portion
            filename = href.split("/")[-1]
            category, name, page = _classify_chart(icao, filename)
            if category is None:
                continue

            # Build the full PDF URL
            pdf_url = EAIP_BASE + f"graphics/eAIP/{filename}"

            plates[category].append({
                "name": name,
                "page": page,
                "url": pdf_url,
            })
            found_count += 1

        print(f" {found_count} charts")

        has_plates = any(plates[c] for c in plates)
        if has_plates:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": apt_name,
                "volume": COUNTRY,
                "plates": plates,
            }

        # Brief pause every 10 airports to avoid hammering the server
        if idx % 10 == 0:
            time.sleep(1)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "belgium", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Belgium skeyes eAIP: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
