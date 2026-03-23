"""Norway Avinor eAIP chart discovery module."""

import os
import re
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, write_outputs

COUNTRY = "norway"
VOLUME = "NO"

AVINOR_ROOT = "https://aim-prod.avinor.no"


def _fetch(url):
    """Fetch a URL and return the text content."""
    try:
        with urlopen(url) as resp:
            return resp.read().decode("utf-8", errors="replace"), resp.url
    except URLError as e:
        raise AIPUnavailableError(f"Norway Avinor unavailable: {url} — {e}")


def _discover_index_and_date():
    """Discover the current Avinor AIP index number and AIRAC date.

    Step 1: GET /no/AIP/ and follow the redirect to extract the index number.
    Step 2: Fetch the history page and extract the AIRAC date string.

    Returns:
        (index, airac_date_str) e.g. (152, "2025-11-06")
    """
    # Step 1: Follow redirect from /no/AIP/ to /no/AIP/View/Index/{INDEX}
    _, final_url = _fetch(f"{AVINOR_ROOT}/no/AIP/")
    m = re.search(r'/no/AIP/View/Index/(\d+)', final_url)
    if not m:
        raise AIPUnavailableError(
            f"Could not extract AIP index from redirect URL: {final_url}"
        )
    index = int(m.group(1))

    # Step 2: Fetch history page to find the AIRAC date
    history_url = (
        f"{AVINOR_ROOT}/no/AIP/View/Index/{index}/history-no-NO.html"
    )
    history_html, _ = _fetch(history_url)

    # Look for href containing YYYY-MM-DD-AIRAC
    date_m = re.search(r'href="[^"]*(\d{4}-\d{2}-\d{2})-AIRAC[^"]*"', history_html)
    if not date_m:
        raise AIPUnavailableError(
            f"Could not find AIRAC date in history page: {history_url}"
        )
    airac_date_str = date_m.group(1)

    return index, airac_date_str


def _build_base_url(index, airac_date_str):
    """Build the Avinor eAIP base URL."""
    return f"{AVINOR_ROOT}/no/AIP/View/Index/{index}/{airac_date_str}-AIRAC/"


def _extract_icao_codes(html):
    """Extract all unique EN** ICAO codes from the airport menu page."""
    codes = re.findall(r'id="AD-2\.(EN[A-Z]{2})"', html)
    seen = set()
    result = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


def _strip_html(text):
    """Remove all HTML tags from a string and normalize whitespace."""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _classify_chart(section_num, chart_name):
    """Classify a chart based on section number and chart name.

    Section 2 → diagram
    Section 4 → departure or star (by name keywords)
    Section 5 → approach
    Sections 3, 6, 7 → skip (return None)

    Returns:
        category string or None if the chart should be skipped.
    """
    if section_num == 2:
        return "diagram"
    if section_num == 4:
        name_upper = chart_name.upper()
        if "DEPARTURE" in name_upper or "SID" in name_upper:
            return "departure"
        if "ARRIVAL" in name_upper or "STAR" in name_upper:
            return "star"
        # Default section 4 to departure if unclassifiable
        return "departure"
    if section_num == 5:
        return "approach"
    # Skip sections 3, 6, 7 and anything else
    return None


def _parse_airport_charts(html, icao):
    """Parse the AD 2.24 section of an airport page and return chart entries.

    Returns:
        list of (category, name, page, numeric_id) tuples
    """
    # Find the AD 2.24 div: <div id="{ICAO}-AD-2.24">
    div_id = f"{icao}-AD-2.24"
    section_match = re.search(
        r'<div[^>]+id="' + re.escape(div_id) + r'"[^>]*>(.*?)(?=<div[^>]+id="|$)',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return []
    section_html = section_match.group(1)

    # Each chart is a <tr> with:
    #   First <td>: <p langSep="NoSep">CHART NAME</p> (may have <ins> tags)
    #   Second <td>: <a href="../../graphics/{ID}.pdf">AD 2 {ICAO} {SECTION} - {PAGE}</a>

    # Find all <tr> blocks within the section
    charts = []
    tr_pattern = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)

    for tr_m in tr_pattern.finditer(section_html):
        tr_html = tr_m.group(1)

        # Extract the chart link: graphics/{ID}.pdf with link text
        link_m = re.search(
            r'href="[^"]*graphics/(\d+)\.pdf"[^>]*>(.*?)</a>',
            tr_html,
            re.DOTALL | re.IGNORECASE,
        )
        if not link_m:
            continue

        numeric_id = link_m.group(1)
        link_text = _strip_html(link_m.group(2))

        # Parse link text: "AD 2 ENGM 5 - 3" or "AD 2 ENGM 2 - 1"
        # Format: "AD 2 {ICAO} {SECTION} - {PAGE}"
        lt_m = re.match(
            r'AD\s+2\s+' + re.escape(icao) + r'\s+(\d+)\s*-\s*(\d+)',
            link_text,
            re.IGNORECASE,
        )
        if not lt_m:
            continue

        section_num = int(lt_m.group(1))
        page_num = lt_m.group(2)

        # Extract chart name from the first <td>'s <p> tag
        # The <p> may contain <ins> or other inline tags — strip all HTML
        p_m = re.search(
            r'<td\b[^>]*>.*?<p\b[^>]*>(.*?)</p>',
            tr_html,
            re.DOTALL | re.IGNORECASE,
        )
        if p_m:
            chart_name = _strip_html(p_m.group(1))
        else:
            chart_name = f"{icao} {section_num}-{page_num}"

        category = _classify_chart(section_num, chart_name)
        if category is None:
            continue

        # Build stable page name: EN_{ICAO}_{SECTION}_{PAGE}
        page = f"EN_{icao}_{section_num}_{page_num}"

        charts.append((category, chart_name, page, numeric_id))

    return charts


def discover(cycle_date, work_dir):
    """Discover all Norway approach charts for the current Avinor AIP cycle.

    Note: cycle_date is accepted for interface compatibility but Norway's index
    and date are discovered dynamically via redirect + history page.
    """
    print("  Discovering Avinor AIP index and AIRAC date...")
    index, airac_date_str = _discover_index_and_date()
    print(f"  Index: {index}, AIRAC date: {airac_date_str}")

    base_url = _build_base_url(index, airac_date_str)
    eaip_url = base_url + "html/eAIP/"
    menu_url = eaip_url + "EN-menu-no-NO.html"

    print(f"  Base URL: {base_url}")
    print("  Fetching airport menu...")
    menu_html, _ = _fetch(menu_url)

    icao_codes = _extract_icao_codes(menu_html)
    print(f"  Found {len(icao_codes)} airports")

    airports = {}

    for i, icao in enumerate(icao_codes):
        apt_url = eaip_url + f"EN-AD-2.{icao}-en-GB.html"
        try:
            apt_html, _ = _fetch(apt_url)
        except AIPUnavailableError:
            print(f"  WARNING: Could not fetch {icao}, skipping")
            if (i + 1) % 10 == 0:
                time.sleep(0.5)
            continue

        chart_entries = _parse_airport_charts(apt_html, icao)

        plates = {"diagram": [], "approach": [], "departure": [], "star": []}

        for category, name, page, numeric_id in chart_entries:
            pdf_url = base_url + f"graphics/{numeric_id}.pdf"
            plates[category].append({
                "name": name,
                "page": page,
                "url": pdf_url,
            })

        has_plates = any(plates[c] for c in plates)
        if has_plates:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": icao,
                "volume": VOLUME,
                "plates": plates,
            }

        # Progress and brief delay to avoid rate limiting
        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(icao_codes)} airports...")
            time.sleep(0.5)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": COUNTRY, "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    # Norway discovers its own AIRAC date; pass None as cycle_date
    result = discover(None, work_dir)
    write_outputs(result, work_dir)
