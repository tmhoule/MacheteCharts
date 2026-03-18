#!/usr/bin/env python3
"""
Build script for Machete Charts MSFS2020 plugin.
Parses NE1.pdf index, extracts plate images, and generates charts.json + layout.json.
"""

import json
import os
import re
import subprocess
import sys

PDF_PATH = "NE1.pdf"
OUTPUT_DIR = "machete-charts"
PAGES_DIR = os.path.join(OUTPUT_DIR, "html_ui", "InGamePanels", "MacheteCharts", "pages")
CHARTS_JSON = os.path.join(OUTPUT_DIR, "html_ui", "InGamePanels", "MacheteCharts", "charts.json")
LAYOUT_JSON = os.path.join(OUTPUT_DIR, "layout.json")

# PDF page offsets
TERMINAL_OFFSET = 146  # terminal chart page N -> PDF page N + 146
STAR_OFFSET = 118      # STAR page ZN -> PDF page N + 118

# Index is on PDF pages 22-31 (K1-K10)
INDEX_FIRST_PAGE = 22
INDEX_LAST_PAGE = 31

DPI = 150
JPEG_QUALITY = 80


def extract_index_text():
    """Extract text from index pages using pdftotext with -layout for column preservation."""
    result = subprocess.run(
        ["pdftotext", "-layout", "-f", str(INDEX_FIRST_PAGE), "-l", str(INDEX_LAST_PAGE),
         PDF_PATH, "-"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Error running pdftotext: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def split_columns(text):
    """Split two-column layout text into two separate line streams.

    In the -layout output, the left column occupies roughly columns 0-86,
    and the right column starts around column 88+. We find the split point
    by looking for the gap between the two NAME headers.
    """
    lines = text.split('\n')
    left_lines = []
    right_lines = []

    # Find the column split position from the header line with two "NAME" entries
    split_col = 88  # default
    for line in lines:
        # Look for the dual-NAME header
        first = line.find('NAME')
        if first >= 0:
            second = line.find('NAME', first + 4)
            if second > first + 10:
                split_col = second
                break

    for line in lines:
        left = line[:split_col].rstrip()
        right = line[split_col:].rstrip() if len(line) > split_col else ''
        if left.strip():
            left_lines.append(left.strip())
        if right.strip():
            right_lines.append(right.strip())

    return left_lines, right_lines


def parse_column(lines):
    """Parse a single column of index lines into airport -> plates mapping.

    Each airport entry in a column follows this order:
      City header (e.g., "AUBURN/LEWISTON, ME")
      Airport facility name with code (e.g., "AUBURN/LEWISTON MUNI(LEW)")
      TAKEOFF MINIMUMS...L
      [procedures]
    """
    airports = {}
    current_code = None
    current_name = None
    current_category = None

    airport_with_code = re.compile(r'^([A-Z][A-Z0-9/ \-\'\.&]+)\(([A-Z0-9]{2,5})\)\s*$')
    standalone_code = re.compile(r'^\(([A-Z0-9]{2,5})\)\s*$')
    proc_page = re.compile(r'^(.+?)\s*\.{2,}\s*(Z?\d+)\s*$')
    city_header = re.compile(r'^[A-Z][A-Z0-9 /\-\']+,\s*[A-Z]{2}\s*$')
    xref = re.compile(r'---SEE\s+')
    skip_set = {'TAKEOFF MINIMUMS', 'ALTERNATE MINIMUMS', 'RADAR MINIMUMS',
                'LAHSO', 'HOT SPOT'}
    prev_line = None  # track previous non-skip line for split name+code

    def is_skip(name):
        return any(s in name.upper() for s in skip_set)

    def add_plate(cat, name, page):
        if current_code is None:
            return
        if current_code not in airports:
            airports[current_code] = {"name": current_name or "", "code": current_code, "plates": {}}
        plates = airports[current_code]["plates"]
        if cat not in plates:
            plates[cat] = []
        plates[cat].append({"name": name, "page": page})

    for line in lines:
        # Skip noise
        if not line:
            continue
        if re.match(r'^K\d+$', line):
            continue
        if line.startswith('INDEX') or line.startswith('26022'):
            continue
        if line.startswith('INDEX OF TERMINAL'):
            continue
        if line.startswith('NE-1,') or line.startswith('NE1'):
            continue
        if line in ('PROC', 'NAME', 'SECT PG'):
            continue
        if xref.search(line):
            continue
        if is_skip(line):
            continue

        # Airport code line (e.g., "AUBURN/LEWISTON MUNI(LEW)")
        m = airport_with_code.match(line)
        if m:
            current_name = m.group(1).strip()
            current_code = m.group(2)
            current_category = None
            if current_code not in airports:
                airports[current_code] = {"name": current_name, "code": current_code, "plates": {}}
            prev_line = line
            continue

        # Standalone code line (e.g., "(BOS)") — name is on the previous line
        sc = standalone_code.match(line)
        if sc:
            current_code = sc.group(1)
            current_name = prev_line if prev_line else ""
            current_category = None
            if current_code not in airports:
                airports[current_code] = {"name": current_name, "code": current_code, "plates": {}}
            prev_line = line
            continue

        # City/state header
        if city_header.match(line):
            prev_line = line
            continue

        # Inline category + procedure: "IAPS ......... ILS OR LOC RWY 04 .........1"
        inline_match = re.match(r'^(IAPS|DPS|STARS?)\s*\.+\s*(.+?)\s*\.{2,}\s*(Z?\d+)\s*$', line)
        if inline_match:
            cat_text = inline_match.group(1)
            proc_name = inline_match.group(2).strip()
            page = inline_match.group(3)
            if cat_text == 'IAPS':
                current_category = 'approach'
            elif cat_text == 'DPS':
                current_category = 'departure'
            elif cat_text.startswith('STAR'):
                current_category = 'star'
            if not is_skip(proc_name):
                add_plate(current_category, proc_name, page)
            continue

        # AIRPORT DIAGRAM with page
        ad_match = re.match(r'^AIRPORT DIAGRAM\s*\.{2,}\s*(\d+)\s*$', line)
        if ad_match:
            current_category = 'diagram'
            add_plate('diagram', 'AIRPORT DIAGRAM', ad_match.group(1))
            continue

        # Bare category header
        cat_match = re.match(r'^(IAPS|DPS|STARS?)\s*$', line)
        if cat_match:
            cat_text = cat_match.group(1)
            if cat_text == 'IAPS':
                current_category = 'approach'
            elif cat_text == 'DPS':
                current_category = 'departure'
            elif cat_text.startswith('STAR'):
                current_category = 'star'
            continue

        # Procedure line with page (continuation)
        pm = proc_page.match(line)
        if pm and current_category:
            proc_name = pm.group(1).strip()
            page = pm.group(2)
            proc_name = re.sub(r'^\.+\s*', '', proc_name).strip()
            if proc_name and not is_skip(proc_name):
                add_plate(current_category, proc_name, page)
            continue

        # Unmatched line — could be a facility name preceding a standalone code
        prev_line = line

    return airports


def parse_index(text):
    """Parse two-column index into merged airport -> plates mapping."""
    left_lines, right_lines = split_columns(text)
    left_airports = parse_column(left_lines)
    right_airports = parse_column(right_lines)

    # Merge: right column airports override/add to left
    airports = left_airports
    for code, data in right_airports.items():
        if code in airports:
            # Merge plates
            for cat, plates in data["plates"].items():
                if cat not in airports[code]["plates"]:
                    airports[code]["plates"][cat] = plates
                else:
                    airports[code]["plates"][cat].extend(plates)
        else:
            airports[code] = data

    return airports


def convert_pages():
    """Convert PDF pages to JPEG images using pdftoppm."""
    os.makedirs(PAGES_DIR, exist_ok=True)

    # Terminal charts: pages 1-446 -> PDF pages 147-592
    # Find the max page from index to know how many to convert
    max_terminal = 446
    max_star = 27

    print(f"Converting terminal chart pages 1-{max_terminal} (PDF {1 + TERMINAL_OFFSET}-{max_terminal + TERMINAL_OFFSET})...")
    for page_num in range(1, max_terminal + 1):
        pdf_page = page_num + TERMINAL_OFFSET
        out_path = os.path.join(PAGES_DIR, str(page_num))
        if os.path.exists(out_path + ".jpg"):
            continue
        subprocess.run([
            "pdftoppm", "-jpeg", "-jpegopt", f"quality={JPEG_QUALITY}",
            "-r", str(DPI), "-f", str(pdf_page), "-l", str(pdf_page),
            "-singlefile", PDF_PATH, out_path
        ], check=True, capture_output=True)
        if page_num % 50 == 0:
            print(f"  ...converted {page_num}/{max_terminal}")

    print(f"Converting STAR pages z1-z{max_star} (PDF {1 + STAR_OFFSET}-{max_star + STAR_OFFSET})...")
    for page_num in range(1, max_star + 1):
        pdf_page = page_num + STAR_OFFSET
        out_path = os.path.join(PAGES_DIR, f"z{page_num}")
        if os.path.exists(out_path + ".jpg"):
            continue
        subprocess.run([
            "pdftoppm", "-jpeg", "-jpegopt", f"quality={JPEG_QUALITY}",
            "-r", str(DPI), "-f", str(pdf_page), "-l", str(pdf_page),
            "-singlefile", PDF_PATH, out_path
        ], check=True, capture_output=True)

    print("Page conversion complete.")


def generate_charts_json(airports):
    """Write charts.json index file."""
    os.makedirs(os.path.dirname(CHARTS_JSON), exist_ok=True)
    with open(CHARTS_JSON, 'w') as f:
        json.dump(airports, f, indent=2)
    print(f"Generated {CHARTS_JSON} with {len(airports)} airports.")


def generate_layout_json():
    """Generate layout.json listing all files with sizes."""
    content = []
    base = OUTPUT_DIR
    for root, dirs, files in os.walk(base):
        for fname in sorted(files):
            if fname == 'layout.json':
                continue
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, base)
            size = os.path.getsize(fpath)
            content.append({
                "path": rel_path.replace(os.sep, '/'),
                "size": size,
                "date": 0
            })

    layout = {"content": content}
    with open(LAYOUT_JSON, 'w') as f:
        json.dump(layout, f, indent=2)
    print(f"Generated {LAYOUT_JSON} with {len(content)} entries.")


def main():
    if not os.path.exists(PDF_PATH):
        print(f"Error: {PDF_PATH} not found in current directory.", file=sys.stderr)
        sys.exit(1)

    print("Step 1: Extracting index text...")
    text = extract_index_text()

    print("Step 2: Parsing index...")
    airports = parse_index(text)

    # Print summary
    total_plates = sum(
        sum(len(plates) for plates in a["plates"].values())
        for a in airports.values()
    )
    print(f"  Found {len(airports)} airports with {total_plates} plates total.")

    # Show a few airports for verification
    for code in list(airports.keys())[:3]:
        a = airports[code]
        cats = {k: len(v) for k, v in a["plates"].items()}
        print(f"  {code} ({a['name']}): {cats}")

    # Step 3 (convert_pages) skipped — images are now hosted remotely at
    # https://hermes-tv.com/MacheteCharts/charts/
    # To regenerate local images, call convert_pages() manually.

    print("\nStep 3: Generating charts.json...")
    generate_charts_json(airports)

    print("\nStep 4: Generating layout.json...")
    generate_layout_json()

    print("\nBuild complete!")


if __name__ == "__main__":
    main()
