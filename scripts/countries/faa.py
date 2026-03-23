"""FAA d-TPP chart discovery module."""

import json
import os
import sys
import xml.etree.ElementTree as ET
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIPUnavailableError, current_airac_date, write_outputs

WANTED = {"APD", "IAP", "DP", "STAR"}
CAT_MAP = {"APD": "diagram", "IAP": "approach", "DP": "departure", "STAR": "star"}


def _cycle_number(cycle_date):
    """Convert AIRAC date to FAA 4-digit cycle number (e.g. 2604).

    FAA uses YYNN format where YY = 2-digit year, NN = cycle number within year.
    """
    year = cycle_date.year
    from base import AIRAC_EPOCH, AIRAC_CYCLE_DAYS
    from datetime import timedelta

    days = (cycle_date - AIRAC_EPOCH).days
    total_cycle = days // AIRAC_CYCLE_DAYS

    jan1 = cycle_date.replace(month=1, day=1)
    days_to_jan1 = (jan1 - AIRAC_EPOCH).days
    first_cycle_of_year = days_to_jan1 // AIRAC_CYCLE_DAYS
    if (jan1 - AIRAC_EPOCH).days % AIRAC_CYCLE_DAYS != 0:
        first_cycle_of_year += 1

    nn = total_cycle - first_cycle_of_year + 1
    yy = year % 100
    return f"{yy:02d}{nn:02d}"


def discover(cycle_date, work_dir):
    """Discover FAA d-TPP charts for the given AIRAC cycle."""
    cycle = _cycle_number(cycle_date)
    base_url = f"https://aeronav.faa.gov/d-tpp/{cycle}/"
    metafile_url = f"{base_url}xml_data/d-tpp_Metafile.xml"

    metafile_path = os.path.join(work_dir, "faa", "d-tpp_Metafile.xml")
    os.makedirs(os.path.dirname(metafile_path), exist_ok=True)

    if not os.path.exists(metafile_path):
        print(f"  Downloading {metafile_url}...")
        try:
            with urlopen(metafile_url) as resp:
                data = resp.read()
            with open(metafile_path, "wb") as f:
                f.write(data)
        except URLError as e:
            raise AIPUnavailableError(f"FAA metafile unavailable: {e}")
    else:
        print("  Metafile already cached.")

    tree = ET.parse(metafile_path)
    root = tree.getroot()
    airports = {}

    for state in root.findall("state_code"):
        for city in state.findall("city_name"):
            volume = city.get("volume")
            for apt in city.findall("airport_name"):
                ident = apt.get("apt_ident")
                name = apt.get("ID")
                icao = apt.get("icao_ident", "")
                if ident not in airports:
                    airports[ident] = {
                        "code": ident, "icao": icao, "name": name, "volume": volume,
                        "plates": {"diagram": [], "approach": [], "departure": [], "star": []},
                    }
                for rec in apt.findall("record"):
                    cc = rec.find("chart_code").text
                    if cc not in WANTED:
                        continue
                    pdf = rec.find("pdf_name").text
                    chart_name = rec.find("chart_name").text
                    if not pdf:
                        continue
                    page = pdf.replace(".PDF", "").replace(".pdf", "")
                    url = base_url + pdf
                    airports[ident]["plates"][CAT_MAP[cc]].append(
                        {"name": chart_name, "page": page, "url": url}
                    )

    result_airports = {}
    for code, apt in sorted(airports.items()):
        has_plates = any(apt["plates"][c] for c in ("diagram", "approach", "departure", "star"))
        if has_plates:
            result_airports[code] = apt

    return {"country": "faa", "airports": result_airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"FAA d-TPP: cycle {_cycle_number(cycle_date)} (effective {cycle_date})")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
