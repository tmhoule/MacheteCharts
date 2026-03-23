"""Germany DFS BasicIFR chart discovery module.

EXPERIMENTAL: Hex hash IDs in DFS BasicIFR URLs change every AIRAC cycle,
requiring a full site crawl on each run. The structure may change without notice.
"""

import os
import re
import sys
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, write_outputs, current_airac_date

COUNTRY = "DE"
BASE_URL = "https://aip.dfs.de/BasicIFR/"
PDF_URL_TEMPLATE = "https://aip.dfs.de/basicIFR/print/AD/{}/chart"
UA = "AIP Download Tool"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _fetch(url):
    """Fetch a URL with custom User-Agent. Returns (text, final_url)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        resp = urllib.request.urlopen(req)
        return resp.read().decode("utf-8", errors="replace"), resp.url
    except urllib.error.URLError as e:
        raise AIPUnavailableError(f"DFS BasicIFR unavailable: {url} — {e}")


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

class _FolderParser(HTMLParser):
    """Parse a DFS chapter/folder page to extract folder and document links.

    Each list item has the structure:
      Folder: <a class="folder-link" href="{HASH}.html">
                <span lang="de" class="folder-name">...</span>
                <span lang="en" class="folder-name">...</span>
              </a>
      Document: <a class="document-link" href="../pages/{HASH}.html">
                  <span lang="de" class="document-name">...</span>
                  <span lang="en" class="document-name">...</span>
                </a>

    We extract the hash from href and take the English (lang="en") span text.
    """

    def __init__(self):
        super().__init__()
        self.folders = []    # list of (hash, name)
        self.documents = []  # list of (hash, name)
        self._in_name_span = False
        self._want_this_span = False   # True only for lang="en" spans
        self._text = ""
        self._href = None
        self._kind = None   # "folder" or "document"

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = d.get("class", "")
        href = d.get("href", "")
        lang = d.get("lang", "")

        if tag == "a":
            if "folder-link" in cls:
                # href is like "{HASH}.html"
                m = re.match(r"([0-9a-f]+)\.html$", href)
                if m:
                    self._href = m.group(1)
                    self._kind = "folder"
            elif "document-link" in cls:
                # href is like "../pages/{HASH}.html"
                m = re.search(r"([0-9A-Fa-f]+)\.html$", href)
                if m:
                    self._href = m.group(1)
                    self._kind = "document"

        elif tag == "span" and self._href:
            if "folder-name" in cls or "document-name" in cls:
                # Only capture the English span
                if lang == "en":
                    self._in_name_span = True
                    self._want_this_span = True
                    self._text = ""
                else:
                    self._in_name_span = True
                    self._want_this_span = False

    def handle_data(self, data):
        if self._in_name_span and self._want_this_span:
            self._text += data

    def handle_endtag(self, tag):
        if tag == "span" and self._in_name_span:
            if self._want_this_span and self._href:
                name = self._text.strip()
                if self._kind == "folder":
                    self.folders.append((self._href, name))
                elif self._kind == "document":
                    self.documents.append((self._href, name))
                # After capturing the English name, reset link state
                self._href = None
                self._kind = None
            self._in_name_span = False
            self._want_this_span = False
            self._text = ""


def _parse_page(html):
    """Parse a DFS chapter/folder page and return (folders, documents)."""
    p = _FolderParser()
    p.feed(html)
    return p.folders, p.documents


# ---------------------------------------------------------------------------
# Chart classification and naming
# ---------------------------------------------------------------------------

def _classify_section(doc_name):
    """Map DFS section number to chart category.

    Section numbering extracted from document names like:
      "AD 2 EDDF 4-2-1 ILS Z CAT II&III RWY 07L"
      prefix:  4  → approach
               2  → diagram
               3  → star
               5  → departure
               1, 6, others → None (skip)
    """
    m = re.search(r"\bAD 2 [A-Z]{4} (\d+)-", doc_name)
    if not m:
        return None
    section = int(m.group(1))
    return {2: "diagram", 3: "star", 4: "approach", 5: "departure"}.get(section)


def _sanitize_page_name(icao, doc_name):
    """Build a sanitized page identifier from a document name.

    Example:
      "AD 2 EDDF 4-2-1 ILS Z CAT II&III RWY 07L" → "DE_EDDF_4_2_1_ILS_Z_RWY_07L"
    """
    # Strip leading "AD 2 ICAO " prefix
    stripped = re.sub(r"^AD 2 [A-Z]{4}\s+", "", doc_name)
    # Drop CAT designators (CAT I, CAT II&III, etc.)
    stripped = re.sub(r"\bCAT\s+[IVX&]+\b", "", stripped, flags=re.IGNORECASE)
    # Replace any non-alphanumeric run with underscore
    sanitized = re.sub(r"[^A-Za-z0-9]+", "_", stripped).strip("_")
    return f"DE_{icao}_{sanitized}"


def _extract_icao(doc_name):
    """Extract ICAO code from a document name like 'AD 2 EDDF 4-2-1 ...'."""
    m = re.search(r"\bAD 2 ([A-Z]{4})\b", doc_name)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# AIRAC and chapter navigation
# ---------------------------------------------------------------------------

def _get_chapter_base_and_root_hash():
    """Follow BasicIFR redirect to discover chapter base URL and root hash.

    Returns: (airac_str, root_hash, chapter_base_url)
      e.g. ("2026MAR19", "b9b9df...", "https://aip.dfs.de/BasicIFR/2026MAR19/chapter/")
    """
    _, final_url = _fetch(BASE_URL)
    # final_url: https://aip.dfs.de/BasicIFR/2026MAR19/chapter/b9b9dfc4aa9df6d88c51f52d6140301f.html
    m = re.search(
        r"(https://aip\.dfs\.de/BasicIFR/(\d{4}[A-Z]{3}\d{2})/chapter/)"
        r"([0-9a-f]+)\.html",
        final_url,
    )
    if not m:
        raise AIPUnavailableError(
            f"DFS BasicIFR: unexpected redirect URL: {final_url}"
        )
    chapter_base = m.group(1)   # ends with "chapter/"
    airac_str = m.group(2)      # e.g. "2026MAR19"
    root_hash = m.group(3)
    return airac_str, root_hash, chapter_base


def _chapter_url(chapter_base, hash_):
    """Build absolute chapter page URL from hash."""
    return f"{chapter_base}{hash_}.html"


# ---------------------------------------------------------------------------
# Main discovery
# ---------------------------------------------------------------------------

def discover(cycle_date, work_dir):
    """Discover all German DFS approach charts for the current AIRAC cycle.

    NOTE: Performs a full site crawl because all resource identifiers are opaque
    hex hashes that change each AIRAC cycle.
    """
    print("  Connecting to DFS BasicIFR...")
    airac_str, root_hash, chapter_base = _get_chapter_base_and_root_hash()
    print(f"  AIRAC: {airac_str}  root hash: {root_hash}")

    # --- root page → find AD chapter ---
    root_html, _ = _fetch(_chapter_url(chapter_base, root_hash))
    root_folders, _ = _parse_page(root_html)

    ad_hash = None
    for h, name in root_folders:
        if re.search(r"\bAD\b", name):
            ad_hash = h
            break
    if not ad_hash:
        raise AIPUnavailableError(
            f"DFS BasicIFR: could not find AD chapter in root page "
            f"(found: {[n for _, n in root_folders]})"
        )
    print(f"  AD chapter hash: {ad_hash}")

    # --- AD page → find AD 2 chapter ---
    ad_html, _ = _fetch(_chapter_url(chapter_base, ad_hash))
    ad_folders, _ = _parse_page(ad_html)

    ad2_hash = None
    for h, name in ad_folders:
        if re.search(r"\bAD 2\b", name):
            ad2_hash = h
            break
    if not ad2_hash:
        raise AIPUnavailableError(
            f"DFS BasicIFR: could not find AD 2 chapter "
            f"(found: {[n for _, n in ad_folders]})"
        )
    print(f"  AD 2 chapter hash: {ad2_hash}")

    # --- AD 2 page → airport folder list ---
    ad2_html, _ = _fetch(_chapter_url(chapter_base, ad2_hash))
    airport_folders, _ = _parse_page(ad2_html)
    print(f"  Found {len(airport_folders)} airport folders")

    airports = {}

    for i, (apt_hash, apt_city) in enumerate(airport_folders):
        # Rate limiting: 0.5s pause every 20 airports
        if i > 0 and i % 20 == 0:
            print(f"  Processed {i}/{len(airport_folders)} airports...")
            time.sleep(0.5)

        try:
            apt_html, _ = _fetch(_chapter_url(chapter_base, apt_hash))
        except AIPUnavailableError:
            print(f"  WARNING: Could not fetch airport folder '{apt_city}', skipping")
            continue

        _, docs = _parse_page(apt_html)
        if not docs:
            continue

        # Derive ICAO from first document whose name matches the pattern
        icao = None
        for _, doc_name in docs:
            icao = _extract_icao(doc_name)
            if icao:
                break
        if not icao:
            continue

        plates = {"diagram": [], "approach": [], "departure": [], "star": []}

        for doc_hash, doc_name in docs:
            category = _classify_section(doc_name)
            if category is None:
                continue
            page = _sanitize_page_name(icao, doc_name)
            url = PDF_URL_TEMPLATE.format(doc_hash)
            plates[category].append({
                "name": doc_name,
                "page": page,
                "url": url,
            })

        if any(plates[c] for c in plates):
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": apt_city,
                "volume": COUNTRY,
                "plates": plates,
            }

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "germany", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Germany DFS BasicIFR: AIRAC {cycle_date} [EXPERIMENTAL]")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
