"""UK NATS eAIP chart discovery module."""

import os
import re
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "uk"
VOLUME = "GB"


def _build_base_url(cycle_date):
    """Build the NATS eAIP base URL for the given AIRAC cycle date."""
    airac_str = cycle_date.strftime("%Y-%m-%d")
    return (
        f"https://www.aurora.nats.co.uk/htmlAIP/Publications/{airac_str}-AIRAC/"
    )


def _fetch(url):
    """Fetch a URL and return the text content."""
    try:
        with urlopen(url) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"UK NATS unavailable: {url} — {e}")


def _extract_icao_codes(html):
    """Extract all unique EG** ICAO codes from the airport index page."""
    codes = re.findall(r'\b(EG[A-Z]{2})\b', html)
    seen = set()
    result = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


def _classify_chart(description):
    """Classify a chart based on its description text.

    Args:
        description: e.g. "INSTRUMENT APPROACH CHART ILS/DME I-AA RWY 09L - ICAO"

    Returns:
        category string or None if the chart should be skipped.
    """
    desc_upper = description.upper()
    if "INSTRUMENT APPROACH CHART" in desc_upper:
        return "approach"
    if "STANDARD DEPARTURE CHART" in desc_upper or "SID" in desc_upper:
        return "departure"
    if "STANDARD ARRIVAL CHART" in desc_upper or "STAR" in desc_upper:
        return "star"
    return None


def _clean_chart_name(description):
    """Extract a concise chart name from the full description text.

    Strips the chart type prefix and trailing "- ICAO" suffix.
    E.g. "INSTRUMENT APPROACH CHART ILS/DME I-AA RWY 09L - ICAO" → "ILS/DME I-AA RWY 09L"
    """
    name = description.strip()

    prefixes = [
        "INSTRUMENT APPROACH CHART",
        "STANDARD DEPARTURE CHART",
        "STANDARD ARRIVAL CHART",
        "AERODROME CHART",
        "AIRCRAFT PARKING/DOCKING CHART",
        "GROUND MOVEMENT CHART",
    ]
    for prefix in prefixes:
        if name.upper().startswith(prefix):
            name = name[len(prefix):].strip()
            break

    # Strip a leading dash
    name = name.lstrip("- ").strip()

    # Strip trailing "- ICAO" or "- ICAO" variants
    name = re.sub(r'\s*-\s*ICAO\s*$', '', name, flags=re.IGNORECASE).strip()

    return name if name else description.strip()


def _parse_airport_charts(html, icao):
    """Parse the AD 2.24 section of an airport page and return chart entries.

    Returns:
        list of (category, name, page, numeric_id) tuples
    """
    # Find the AD 2.24 section
    # Look for a section heading containing "AD 2.24" and capture up to next major section
    section_match = re.search(
        r'AD\s+2\.24.+?(?=AD\s+2\.25|\Z)',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        # Fallback: search the whole page for graphics links
        section_html = html
    else:
        section_html = section_match.group(0)

    # Find all chart links with their numeric IDs and link text
    # Pattern: <a href="../../graphics/{ID}.pdf">AD 2.ICAO-TYPE-SEQ</a>
    link_pattern = re.compile(
        r'href="[^"]*graphics/(\d+)\.pdf"[^>]*>(AD\s+2\.[^<]+)</a>',
        re.IGNORECASE,
    )

    # Find all <p> text blocks (chart descriptions)
    # We pair them in document order: each <p> description precedes its chart link
    # Strategy: find positions of all <p> texts and all chart links, then pair them
    desc_pattern = re.compile(r'<p[^>]*>([^<]+)</p>', re.IGNORECASE)

    # Build an ordered list of (position, type, value) for descriptions and links
    items = []

    for m in desc_pattern.finditer(section_html):
        text = m.group(1).strip()
        if text:
            items.append((m.start(), 'desc', text))

    for m in link_pattern.finditer(section_html):
        numeric_id = m.group(1)
        link_text = m.group(2).strip()
        items.append((m.start(), 'link', (numeric_id, link_text)))

    # Sort by position
    items.sort(key=lambda x: x[0])

    # Pair each link with the most recent preceding description
    charts = []
    last_desc = None

    for pos, item_type, value in items:
        if item_type == 'desc':
            last_desc = value
        elif item_type == 'link' and last_desc is not None:
            numeric_id, link_text = value

            # Classify based on description
            # link_text looks like "AD 2.EGLL-8-1" — type number is the first digit after ICAO-
            link_m = re.match(r'AD\s+2\.' + re.escape(icao) + r'-(\d+)-(\d+)', link_text, re.IGNORECASE)
            if link_m:
                type_num = link_m.group(1)
                seq_num = link_m.group(2)
                # Type 2 = aerodrome/ground chart → diagram
                # Type 3,4,5 = local area, CTR, surveillance → skip
                if type_num in ("3", "4", "5"):
                    last_desc = None
                    continue
                if type_num == "2":
                    category = "diagram"
                else:
                    category = _classify_chart(last_desc)
                    if category is None:
                        last_desc = None
                        continue
            else:
                # Non-standard link text — classify by description
                category = _classify_chart(last_desc)
                if category is None:
                    last_desc = None
                    continue

            name = _clean_chart_name(last_desc)

            # Build a stable page name from the link text
            # "AD 2.EGLL-8-1" → "AD_2_EGLL_8_1"
            page = re.sub(r'[\s\-\.]+', '_', link_text.strip())

            charts.append((category, name, page, numeric_id))
            last_desc = None  # consume the description

    return charts


def discover(cycle_date, work_dir):
    """Discover all UK approach charts for the given AIRAC cycle."""
    base_url = _build_base_url(cycle_date)
    eaip_url = base_url + "html/eAIP/"
    index_url = eaip_url + "EG-AD-1.3-en-GB.html"

    print(f"  Base URL: {base_url}")
    print(f"  Fetching airport index...")
    index_html = _fetch(index_url)

    icao_codes = _extract_icao_codes(index_html)
    print(f"  Found {len(icao_codes)} airports")

    airports = {}

    for i, icao in enumerate(icao_codes):
        apt_url = eaip_url + f"EG-AD-2.{icao}-en-GB.html"
        try:
            apt_html = _fetch(apt_url)
        except AIPUnavailableError:
            print(f"  WARNING: Could not fetch {icao}, skipping")
            # Rate limit delay even on failure
            if (i + 1) % 20 == 0:
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
                "name": icao,  # NATS index page uses ICAO codes; name set to ICAO
                "volume": VOLUME,
                "plates": plates,
            }

        # Progress + brief delay to avoid rate limiting
        if (i + 1) % 20 == 0:
            print(f"  Processed {i + 1}/{len(icao_codes)} airports...")
            time.sleep(0.5)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": COUNTRY, "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"UK NATS: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
