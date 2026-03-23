"""Iceland Isavia eAIP chart discovery module."""

import os
import re
import sys
import time
from urllib.parse import quote
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, write_outputs

COUNTRY = "iceland"
VOLUME = "BI"

BASE_URL = "https://eaip.isavia.is/"

# Known Iceland ICAO airport codes (BI prefix)
ICELAND_AIRPORTS = [
    "BIAR", "BIBD", "BIEG", "BIGJ", "BIGR",
    "BIHN", "BIHU", "BIIS", "BIKF", "BIKR",
    "BIRK", "BITN", "BIVM", "BIVO",
]

# PART section number → chart category; sections 3, 4, 8 are skipped
PART_CATEGORY = {
    2: "diagram",
    5: "star",
    6: "approach",
    7: "departure",
}

# Prefix of all Iceland chart PDF paths (relative to eAIP/)
CHARTS_ROOT = "../documents/Root_WePub/Rep_ISAVIA/Charts/AD/"


def _fetch(url):
    """Fetch a URL and return the text content."""
    try:
        with urlopen(url) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except URLError as e:
        raise AIPUnavailableError(f"Iceland Isavia unavailable: {url} — {e}")


def _discover_airac_path():
    """Fetch the Isavia eAIP landing page and extract the current AIRAC path.

    The landing page table lists the currently effective issue first with a
    link like: href="https://eaip.isavia.is/A_03-2026_2026_03_19/"

    Returns:
        AIRAC path string, e.g. "A_03-2026_2026_03_19"
    """
    html = _fetch(BASE_URL)
    matches = re.findall(r'href="[^"]*?(A_\d{2}-\d{4}_\d{4}_\d{2}_\d{2})[^"]*"', html)
    if not matches:
        raise AIPUnavailableError(
            "Could not find AIRAC path on Isavia eAIP landing page"
        )
    # First match is the currently effective issue
    return matches[0]


def _parse_airport_section_pages(menu_html, icao_list):
    """Parse the eAIP menu HTML and extract section page filenames per airport.

    The menu contains hrefs like (single-quoted):
      'BI-AD BIKF KEFLAVÍK - KEFLAVIK 6-en-GB.html#...'

    We collect the filename (before '#') for each airport and section number
    that is in PART_CATEGORY.

    Args:
        menu_html: full HTML of the eAIP/menu.html page
        icao_list: list of ICAO codes to collect

    Returns:
        airport_sections: {icao: {part_num: page_filename, ...}}
        airport_names:    {icao: english_name_string}
    """
    icao_set = set(icao_list)
    # Match: href='BI-AD {ICAO} <anything> {N}-en-GB.html...'
    # Use alternation on the ICAO codes for precision
    icao_alt = "|".join(re.escape(c) for c in sorted(icao_set))
    pattern = re.compile(
        r"href='(BI-AD\s+(" + icao_alt + r")\s+[^']*?(\d+)-en-GB\.html)[^']*'",
        re.IGNORECASE,
    )

    airport_sections = {}  # {icao: {part_num: filename}}
    airport_names = {}     # {icao: english_name}

    for m in pattern.finditer(menu_html):
        full_href = m.group(1)       # e.g. "BI-AD BIKF KEFLAVÍK - KEFLAVIK 6-en-GB.html"
        icao = m.group(2).upper()
        part_num = int(m.group(3))

        if part_num not in PART_CATEGORY:
            continue

        if icao not in airport_sections:
            airport_sections[icao] = {}

        # Only record the first occurrence of each section per airport
        if part_num not in airport_sections[icao]:
            airport_sections[icao][part_num] = full_href

        # Extract English airport name from the " - ASCII_NAME N" portion
        if icao not in airport_names:
            name_m = re.search(r"\s+-\s+([A-Z][A-Z0-9 ]+?)\s+\d+-en-GB\.html", full_href)
            if name_m:
                airport_names[icao] = name_m.group(1).strip().title()
            else:
                airport_names[icao] = icao

    return airport_sections, airport_names


def _extract_charts_from_section(html, airac_path, icao):
    """Parse a section HTML page and return a list of plate dicts.

    Matches any PDF link under Charts/AD/{ICAO}/:
      href="../documents/Root_WePub/Rep_ISAVIA/Charts/AD/{ICAO}/{path}/{filename}.pdf"

    Some airports place PDFs directly in Charts/AD/{ICAO}/ (no subdirectory);
    others use PART_{N}/ subdirectories. Both forms are handled.

    The category is determined by the section page the link appears on (the
    caller passes the appropriate category from PART_CATEGORY).

    Args:
        html: page HTML content
        airac_path: e.g. "A_03-2026_2026_03_19"
        icao: airport ICAO code

    Returns:
        List of plate dicts: [{"name": str, "page": str, "url": str}]
    """
    # Match any PDF under Charts/AD/{ICAO}/ (with or without subdirectory)
    charts_prefix = re.escape(CHARTS_ROOT + icao + "/")
    pattern = re.compile(
        r'href="(' + charts_prefix + r'([^"]+\.pdf))"',
        re.IGNORECASE,
    )

    plates = []
    seen_pages = set()

    for m in pattern.finditer(html):
        rel_href = m.group(1)   # e.g. "../documents/.../BIKF/PART_6/BIKF_6_RNP_RWY_01.pdf"
        rest = m.group(2)       # e.g. "PART_6/BIKF_6_RNP_RWY_01.pdf" or "BIBD_6_RNP_A.pdf"

        # Filename is the last path component
        filename = rest.split("/")[-1]  # e.g. "BIKF_6_RNP_RWY_01.pdf"

        # Page name: strip .pdf, replace spaces with underscores
        page = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
        page = page.replace(" ", "_")

        if page in seen_pages:
            continue
        seen_pages.add(page)

        # Human-readable name: strip .pdf, underscores/spaces to spaces,
        # drop the leading "ICAO PART_NUM " prefix (e.g. "BIKF 6 " or "BIBD 6 ")
        name = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
        name = name.replace("_", " ")
        name = re.sub(r"^" + re.escape(icao) + r"\s+\d+\s+", "", name).strip()
        # If name is now empty or just the icao, fall back to the full stem
        if not name:
            name = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE).replace("_", " ")

        # Resolve relative href "../documents/..." (relative to eAIP/) to absolute URL.
        # Going up one level from eAIP/ gives {BASE_URL}{airac_path}/
        doc_path = rel_href.replace("../documents/", "documents/", 1)
        pdf_url = BASE_URL + airac_path + "/" + quote(doc_path, safe="/:")

        plates.append({
            "name": name,
            "page": page,
            "url": pdf_url,
        })

    return plates


def discover(cycle_date, work_dir):
    """Discover all Iceland approach charts for the current Isavia eAIP cycle.

    cycle_date is accepted for API compatibility but the AIRAC path is
    discovered dynamically from the Isavia eAIP landing page.
    """
    print("  Discovering current AIRAC from Isavia eAIP landing page...")
    airac_path = _discover_airac_path()
    print(f"  AIRAC path: {airac_path}")

    eaip_base = BASE_URL + airac_path + "/eAIP/"
    menu_url = eaip_base + "menu.html"
    print(f"  Fetching menu (~5MB)...")
    menu_html = _fetch(menu_url)
    print(f"  Menu size: {len(menu_html) / 1024:.0f} KB")

    airport_sections, airport_names = _parse_airport_section_pages(
        menu_html, ICELAND_AIRPORTS
    )
    print(f"  Found section pages for {len(airport_sections)} airports")

    airports = {}

    for i, icao in enumerate(ICELAND_AIRPORTS):
        sections = airport_sections.get(icao, {})
        plates = {"diagram": [], "approach": [], "departure": [], "star": []}
        any_charts = False

        for part_num in sorted(PART_CATEGORY.keys()):
            page_filename = sections.get(part_num)
            if not page_filename:
                continue

            # URL-encode the filename (may contain Icelandic chars like Í, Ö, Þ)
            sec_url = eaip_base + quote(page_filename, safe="")
            try:
                sec_html = _fetch(sec_url)
            except AIPUnavailableError:
                continue

            sec_plates = _extract_charts_from_section(sec_html, airac_path, icao)
            category = PART_CATEGORY[part_num]
            for plate in sec_plates:
                plates[category].append(plate)
                any_charts = True

        if any_charts:
            name = airport_names.get(icao, icao)
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": name,
                "volume": VOLUME,
                "plates": plates,
            }

        if (i + 1) % 5 == 0:
            print(f"  Processed {i + 1}/{len(ICELAND_AIRPORTS)} airports...")
        time.sleep(0.2)

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": COUNTRY, "airports": airports}


if __name__ == "__main__":
    from base import current_airac_date

    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Iceland Isavia eAIP: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
