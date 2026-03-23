"""Shared utilities for MacheteCharts country modules."""

import json
import os
from datetime import date, timedelta

# Known AIRAC effective date (reference epoch)
AIRAC_EPOCH = date(2020, 1, 2)
AIRAC_CYCLE_DAYS = 28


class AIPUnavailableError(Exception):
    """Raised when a country's AIP is unreachable for the requested cycle."""
    pass


def current_airac_date(ref_date=None):
    """Compute the most recent AIRAC effective date on or before ref_date.

    Args:
        ref_date: date to compute from (default: today)

    Returns:
        datetime.date of the AIRAC cycle effective date
    """
    if ref_date is None:
        ref_date = date.today()
    days_since = (ref_date - AIRAC_EPOCH).days
    cycles = days_since // AIRAC_CYCLE_DAYS
    return AIRAC_EPOCH + timedelta(days=cycles * AIRAC_CYCLE_DAYS)


def write_outputs(result, work_dir):
    """Write _download_list.txt and charts.json from a discover() result.

    Args:
        result: dict with "country" key (CLI-friendly name like "france", "faa")
                and "airports" key from discover()
        work_dir: directory to write outputs into (created if needed)

    The "country" key must match the CLI argument / module filename (e.g. "france",
    not "FR") so the orchestrator can find the output files.
    """
    country = result["country"]
    country_dir = os.path.join(work_dir, country)
    os.makedirs(country_dir, exist_ok=True)

    # Write download list: full_url|volume|page_name
    dl_path = os.path.join(country_dir, "_download_list.txt")
    with open(dl_path, "w") as f:
        for code, apt in sorted(result["airports"].items()):
            for cat in ("diagram", "approach", "departure", "star"):
                for plate in apt.get("plates", {}).get(cat, []):
                    f.write(f"{plate['url']}|{apt['volume']}|{plate['page']}\n")

    # Write charts.json fragment (without url fields in plates)
    index = {}
    for code, apt in sorted(result["airports"].items()):
        plates = {}
        for cat in ("diagram", "approach", "departure", "star"):
            cat_plates = apt.get("plates", {}).get(cat, [])
            if cat_plates:
                plates[cat] = [{"name": p["name"], "page": p["page"]} for p in cat_plates]
        if plates:
            index[code] = {
                "code": apt["code"],
                "icao": apt["icao"],
                "name": apt["name"],
                "volume": apt["volume"],
                "plates": plates,
            }

    json_path = os.path.join(country_dir, "charts.json")
    with open(json_path, "w") as f:
        json.dump(index, f, separators=(",", ":"))

    dl_count = sum(
        len(apt.get("plates", {}).get(cat, []))
        for apt in result["airports"].values()
        for cat in ("diagram", "approach", "departure", "star")
    )
    print(f"  {len(index)} airports, {dl_count} charts")
    print(f"  charts.json: {os.path.getsize(json_path) / 1024:.1f} KB")
