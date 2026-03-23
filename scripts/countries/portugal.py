"""Portugal NAV Portugal eAIP chart discovery module."""

import os
import re
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, write_outputs, current_airac_date

COUNTRY = "PT"

# Base URL uses eAIP_Current symlink — always points to the current AIRAC cycle.
BASE_URL = (
    "https://ais.nav.pt/wp-content/uploads/AIS_Files/"
    "eAIP_Current/eAIP_Online/eAIP/"
)

# Section number → chart category.
# Skipped: 04 (obstacle), 06 (precision approach terrain), 11 (surveillance
# minimum altitude), 14 (and others not listed below).
SECTION_CATEGORY = {
    "01": "diagram",   # Aerodrome Chart
    "02": "diagram",   # Aircraft Parking/Docking Chart
    "03": "diagram",   # Aerodrome Ground Movement Chart
    "08": "departure", # SID
    "10": "star",      # STAR
    "12": "approach",  # Instrument Approach Chart (ILS, LOC, RNP)
    "13": "approach",  # Visual Approach Chart
}


def _fetch(url):
    """Fetch a URL and return the decoded text content.

    NAV Portugal's server blocks Python's default urllib User-Agent with a
    403, but accepts standard browser-like and curl User-Agents.
    """
    req = Request(url, headers={"User-Agent": "curl/8.7.1"})
    try:
        with urlopen(req) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"Portugal NAV unavailable: {url} — {e}")


def _discover_airports(menu_html):
    """Extract (icao, name) pairs from the eAIP menu HTML.

    The menu contains text like ``> LPCS CASCAIS <`` near each airport
    entry.  We de-duplicate on ICAO code and stop the name at any junk.

    Returns:
        list of (icao, name) tuples in menu order.
    """
    seen = set()
    airports = []
    for m in re.finditer(r">\s*(LP[A-Z]{2})\s+([A-Z][A-Z ]+)", menu_html):
        icao, raw_name = m.groups()
        if icao in seen:
            continue
        name = raw_name.strip()
        # Discard entries whose "name" looks like a section heading rather
        # than an airport name (e.g. "RUNWAY SURFACE CONDITION…").
        if len(name) > 40 or name.isupper() and " " in name and len(name.split()) > 4:
            continue
        seen.add(icao)
        airports.append((icao, name))
    return airports


def _extract_charts(icao, apt_html):
    """Return plates dict extracted from an airport's eAIP HTML page.

    Charts follow the URL pattern:
        graphics/eAIP/LP_AD_2_{ICAO}_{SS}-{N}_en.pdf

    The chart title appears in the visible text immediately before the
    ``<a href="...">`` tag for each PDF, so we scan backwards from each
    PDF match to collect the preceding text content.

    Returns:
        dict with keys "diagram", "approach", "departure", "star", each
        holding a list of {"name": ..., "page": ..., "url": ...} dicts.
    """
    plates = {"diagram": [], "approach": [], "departure": [], "star": []}

    # Regex for the numbered-section PDFs: LP_AD_2_ICAO_SS-N_en.pdf
    pdf_pattern = re.compile(
        rf"graphics/eAIP/LP_AD_2_{icao}_(\d{{2}})-(\d+)_en\.pdf"
    )

    # We scan the whole document once, keeping a sliding window of stripped
    # text so we can extract the chart title that precedes each PDF link.
    # Strategy: split on each PDF occurrence and look at what came before.
    seen_pages = set()
    for m in pdf_pattern.finditer(apt_html):
        ss, page_num = m.group(1), m.group(2)
        category = SECTION_CATEGORY.get(ss)
        if category is None:
            continue

        page = f"LP_AD_2_{icao}_{ss}-{page_num}_en"
        if page in seen_pages:
            continue
        seen_pages.add(page)

        url = BASE_URL + m.group(0)

        # Extract the chart title from the text that precedes this PDF link.
        # We look at up to 600 chars of raw HTML before the match, strip tags,
        # and take the last meaningful text chunk (split on the previous PDF
        # reference so we don't bleed across entries).
        pre_html = apt_html[max(0, m.start() - 600): m.start()]
        # Cut at the last previous PDF reference to avoid cross-entry bleed.
        last_pdf = pre_html.rfind(".pdf")
        if last_pdf != -1:
            pre_html = pre_html[last_pdf + 4:]
        # Strip HTML tags and collapse whitespace.
        pre_text = re.sub(r"<[^>]+>", " ", pre_html)
        pre_text = re.sub(r"\s+", " ", pre_text).strip()
        # Remove path fragments like "../graphics/eAIP/..." that can leak
        # through as link text.
        pre_text = re.sub(r"\.\./graphics/eAIP/[^\s]*", "", pre_text).strip()
        # Drop any trailing partial opening tag artifacts (e.g. "<a id=...").
        pre_text = re.sub(r"<\s*\w.*$", "", pre_text, flags=re.DOTALL).strip()
        # Drop leading table-cell attribute noise (e.g. 'left btop bright…>Page',
        # or 'tr>' from a table row closing tag).
        pre_text = re.sub(r'^[^>]*>\s*', "", pre_text).strip()
        # Also strip the bare 'Page' prefix that sometimes remains.
        pre_text = re.sub(r'^Page\s+', "", pre_text).strip()

        if pre_text:
            name = pre_text
        else:
            # Fallback: construct a generic name from the page identifier.
            name = page.replace("_", " ")

        plates[category].append({"name": name, "page": page, "url": url})

    return plates


def discover(cycle_date, work_dir):
    """Discover all Portuguese approach charts for the current AIRAC cycle.

    The eAIP_Current symlink at NAV Portugal always resolves to the live
    cycle, so cycle_date is accepted for interface consistency but not used
    to build the URL.

    Args:
        cycle_date: datetime.date (unused — URL is cycle-independent)
        work_dir:   output directory passed through to write_outputs()

    Returns:
        dict with "country" and "airports" keys as expected by write_outputs().
    """
    eaip_url = BASE_URL + "html/eAIP/"
    menu_url = eaip_url + "LP-menu-en-PT.html"

    print(f"  Base URL: {BASE_URL}")
    print(f"  Fetching menu: {menu_url}")
    menu_html = _fetch(menu_url)

    raw_airports = _discover_airports(menu_html)
    print(f"  Found {len(raw_airports)} airports in menu")

    airports = {}

    for i, (icao, name) in enumerate(raw_airports):
        apt_url = eaip_url + f"LP-AD-2.{icao}-en-PT.html"
        try:
            apt_html = _fetch(apt_url)
        except AIPUnavailableError:
            print(f"  WARNING: Could not fetch {icao}, skipping")
            continue

        plates = _extract_charts(icao, apt_html)
        has_plates = any(plates[c] for c in plates)

        if has_plates:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": name,
                "volume": COUNTRY,
                "plates": plates,
            }

        # Progress + brief delay to be polite to the server.
        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(raw_airports)} airports...")
            time.sleep(0.5)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "portugal", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Portugal NAV: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
