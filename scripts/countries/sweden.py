"""Sweden LFV eAIP chart discovery module."""

import json
import os
import re
import sys
import time
from urllib.parse import quote
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, write_outputs

COUNTRY = "SE"

# Sections of interest: section number → category hint
SECTIONS_OF_INTEREST = {2, 6, 8}

# Skip these section numbers
SECTIONS_SKIP = {3, 5, 7, 9}

AIRAC_DISCOVERY_URL = "https://aro.lfv.se/content/eaip/default_offline.html"


def _fetch(url):
    """Fetch a URL and return the text content."""
    try:
        with urlopen(url) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"Sweden LFV unavailable: {url} — {e}")


def _discover_airac_base_url():
    """Fetch the LFV eAIP index and extract the current AIRAC base URL.

    Parses the "Currently Effective Issue" table for a link like:
        href="AIRAC AIP AMDT 2-2026_2026_03_19\\index-v2.html"

    Returns the base URL, e.g.:
        https://aro.lfv.se/content/eaip/AIRAC%20AIP%20AMDT%202-2026_2026_03_19/
    """
    html = _fetch(AIRAC_DISCOVERY_URL)
    # Match href with optional backslash path separator
    m = re.search(r'href="(AIRAC AIP AMDT [^"\\]+)[\\"]', html)
    if not m:
        raise AIPUnavailableError("Could not find current AIRAC link on LFV default_offline page")
    raw_path = m.group(1)
    # Normalize: strip any trailing path component (like index-v2.html) if present
    # The path is something like: AIRAC AIP AMDT 2-2026_2026_03_19
    folder = raw_path.strip()
    base_url = "https://aro.lfv.se/content/eaip/" + quote(folder, safe="") + "/"
    return base_url


def _parse_datasource(js_text):
    """Parse datasource.js and return list of (icao, name, section_hrefs) tuples.

    section_hrefs is a dict: {section_num: href_relative_to_eAIP}
    e.g. {2: "ES-AD 2 ESSA STOCKHOLM-ARLANDA 2-en-GB.html#...", 6: ..., 8: ...}
    """
    # Strip JS variable declaration and trailing semicolon
    json_str = re.sub(r"^\s*const DATASOURCE\s*=\s*", "", js_text.strip())
    if json_str.endswith(";"):
        json_str = json_str[:-1]

    ds = json.loads(json_str)

    # Navigate to Part 3 / AD 2 in en-GB
    menu = ds["tabs"][0]["contents"]["en-GB"]["menu"]
    part3 = next(
        (item for item in menu if "PART 3" in item.get("id", "")),
        None,
    )
    if part3 is None:
        raise AIPUnavailableError("Could not find Part 3 (Aerodrome) in datasource.js")

    ad2 = next(
        (ch for ch in part3.get("children", []) if ch.get("id", "").startswith("AD 2")),
        None,
    )
    if ad2 is None:
        raise AIPUnavailableError("Could not find AD 2 section in datasource.js")

    airports = []
    for apt_node in ad2.get("children", []):
        # Extract ICAO from node id, e.g. "AD 2 ESSA STOCKHOLM-ARLANDAen-GB"
        m = re.search(r"AD 2 (ES[A-Z]{2})\b", apt_node.get("id", ""))
        if not m:
            continue
        icao = m.group(1)

        # Extract airport name from title: "AD 2 ESSA STOCKHOLM-ARLANDA "
        title = apt_node.get("title", "")
        name_m = re.sub(r"^AD 2 ES[A-Z]{2}\s*", "", title).strip()
        name = name_m if name_m else icao

        # Map section number → href
        section_hrefs = {}
        for sec_node in apt_node.get("children", []):
            sec_id = sec_node.get("id", "")
            # Section id looks like "AD 2 ESSA STOCKHOLM-ARLANDA 6en-GB"
            sec_m = re.search(r" (\d+)en-GB$", sec_id)
            if not sec_m:
                continue
            sec_num = int(sec_m.group(1))
            if sec_num in SECTIONS_OF_INTEREST:
                href = sec_node.get("href", "")
                # Strip the anchor fragment — we want just the filename
                href_file = href.split("#")[0]
                if href_file:
                    section_hrefs[sec_num] = href_file

        airports.append((icao, name, section_hrefs))

    return airports


def _classify_section(section_num, pdf_path, span_title):
    """Determine chart category from section number and title/filename.

    Returns one of: "diagram", "approach", "departure", "star", or None.
    """
    if section_num == 2:
        return "diagram"
    if section_num == 8:
        return "approach"
    if section_num == 6:
        # SID and STAR are combined in section 6 — classify by title/filename
        combined = (span_title + " " + pdf_path).upper()
        if "STAR" in combined:
            return "star"
        if "SID" in combined:
            return "departure"
        # Fallback: treat as departure
        return "departure"
    return None


def _extract_charts_from_section(html, section_num, base_url):
    """Parse a section HTML page and return a list of plate dicts.

    Each plate: {"name": str, "page": str, "url": str}
    """
    # Pattern: T2_default span (title) immediately followed by ulink anchor (pdf)
    pattern = (
        r'<span class="T2_default"[^>]*>([^<]+)</span>'
        r'.*?'
        r'<a class="ulink" href="(\.\./documents/[^"]+\.pdf)"'
    )
    matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)

    plates = []
    seen_pages = set()

    for span_title, rel_href in matches:
        span_title = span_title.strip()
        # rel_href: "../documents/Root/SWEDEN/Charts/AD/ESSA/8. IAC/ESSA ILS or LOC RWY 01L.pdf"
        # Resolve: replace ../documents/ with {base_url}documents/
        doc_path = rel_href.replace("../documents/", "documents/", 1)
        pdf_url = base_url + quote(doc_path, safe="/:.")

        # Derive page name from the PDF filename (spaces → underscores)
        filename = os.path.basename(rel_href)
        page = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
        page = page.replace(" ", "_")

        if page in seen_pages:
            continue
        seen_pages.add(page)

        category = _classify_section(section_num, rel_href, span_title)
        if category is None:
            continue

        # Use the span title as the human-readable chart name
        name = span_title

        plates.append({
            "category": category,
            "name": name,
            "page": page,
            "url": pdf_url,
        })

    return plates


def discover(cycle_date, work_dir):
    """Discover all Swedish approach charts for the given AIRAC cycle.

    cycle_date is accepted for API compatibility but LFV always serves the
    currently effective AIRAC — we discover the live base URL from the index.
    """
    print("  Discovering current AIRAC from LFV eAIP index...")
    base_url = _discover_airac_base_url()
    print(f"  Base URL: {base_url}")

    datasource_url = base_url + "v2/js/datasource.js"
    print("  Fetching datasource.js (~3MB)...")
    js_text = _fetch(datasource_url)
    print(f"  datasource.js size: {len(js_text) / 1024:.0f} KB")

    airport_list = _parse_datasource(js_text)
    print(f"  Found {len(airport_list)} airports in AD 2")

    airports = {}

    for i, (icao, name, section_hrefs) in enumerate(airport_list):
        plates = {"diagram": [], "approach": [], "departure": [], "star": []}
        any_charts = False

        for sec_num, href_file in sorted(section_hrefs.items()):
            # URL-encode the href filename (contains spaces, special chars)
            sec_url = base_url + "eAIP/" + quote(href_file, safe="")
            try:
                sec_html = _fetch(sec_url)
            except AIPUnavailableError as e:
                print(f"  WARNING: {icao} section {sec_num} fetch failed: {e}")
                continue

            sec_plates = _extract_charts_from_section(sec_html, sec_num, base_url)
            for plate in sec_plates:
                cat = plate["category"]
                plates[cat].append({
                    "name": plate["name"],
                    "page": plate["page"],
                    "url": plate["url"],
                })
                any_charts = True

        if any_charts:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": name,
                "volume": COUNTRY,
                "plates": plates,
            }

        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(airport_list)} airports...")
            time.sleep(0.5)
        else:
            time.sleep(0.1)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "sweden", "volume": COUNTRY, "airports": airports}


if __name__ == "__main__":
    from base import current_airac_date

    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Sweden LFV eAIP: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
