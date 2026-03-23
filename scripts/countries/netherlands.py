"""Netherlands LVNL eAIP chart discovery module.

HTML pages are behind Cloudflare JS challenge (return 403).
PDFs are directly accessible, so we probe candidate URLs with HEAD requests.
"""

import os
import sys
import urllib.request
from urllib.error import URLError

sys.path.insert(0, os.path.dirname(__file__))
from base import AIRAC_EPOCH, AIRAC_CYCLE_DAYS, AIPUnavailableError, current_airac_date, write_outputs

COUNTRY = "NL"

AIRPORTS = {
    "EHAM": "Amsterdam Schiphol",
    "EHRD": "Rotterdam The Hague",
    "EHEH": "Eindhoven",
    "EHGG": "Groningen Eelde",
    "EHBK": "Maastricht Aachen",
    "EHBD": "Woensdrecht",
    "EHLE": "Lelystad",
    "EHKD": "De Kooy Den Helder",
    "EHTW": "Enschede Twente",
    "EHTL": "Terlet",
    "EHTE": "Teuge",
    "EHHV": "Hilversum",
    "EHDR": "Drachten",
    "EHSE": "Seppe",
    "EHMZ": "Midden-Zeeland",
    "EHOW": "Oostwold",
    "EHST": "Stadskanaal",
}

RUNWAYS = [
    "04", "05", "06", "08", "09", "10", "14", "18", "18C", "18L", "18R",
    "21", "22", "23", "24", "25", "27", "28", "32", "36", "36C", "36L", "36R",
    "03", "04L", "04R", "07", "11", "12", "15", "19", "20", "26", "29", "33",
]

CHART_TYPE_MAP = {
    "ADC": "diagram",
    "GMC": "diagram",
    "IAC": "approach",
    "SID": "departure",
    "STAR": "star",
}


def _amendment_number(cycle_date):
    """Compute the AIRAC amendment number within the year (01-13)."""
    jan1 = cycle_date.replace(month=1, day=1)
    days_to_jan1 = (jan1 - AIRAC_EPOCH).days
    first_cycle = days_to_jan1 // AIRAC_CYCLE_DAYS
    if (jan1 - AIRAC_EPOCH).days % AIRAC_CYCLE_DAYS != 0:
        first_cycle += 1
    total_cycle = (cycle_date - AIRAC_EPOCH).days // AIRAC_CYCLE_DAYS
    return total_cycle - first_cycle + 1


def _build_base_url(cycle_date):
    """Build the LVNL eAIP base URL for the given AIRAC cycle date."""
    nn = _amendment_number(cycle_date)
    yyyy = cycle_date.year
    mm = cycle_date.month
    dd = cycle_date.day
    amdt = f"AIRAC%20AMDT%20{nn:02d}-{yyyy}_{yyyy}_{mm:02d}_{dd:02d}"
    return (
        f"https://eaip.lvnl.nl/web/eaip/{amdt}/documents/Root_WePub/Charts/AD/"
    )


def _candidate_filenames(icao):
    """Generate all candidate PDF filenames for an airport."""
    candidates = []

    # Basic charts
    for suffix in ("ADC", "GMC", "STAR", "VFR-PROC"):
        candidates.append(f"{icao}-{suffix}.pdf")

    # SID overview
    candidates.append(f"{icao}-SID-OV.pdf")

    # Runway-specific charts
    for rwy in RUNWAYS:
        candidates.append(f"{icao}-SID-{rwy}.pdf")
        candidates.append(f"{icao}-IAC-{rwy}-ILS-LOC.pdf")
        candidates.append(f"{icao}-IAC-{rwy}-ILS-LOC-CATH.pdf")
        candidates.append(f"{icao}-IAC-{rwy}-RNP.pdf")
        candidates.append(f"{icao}-IAC-{rwy}-VOR.pdf")
        candidates.append(f"{icao}-IAC-{rwy}-NDB.pdf")

    return candidates


def _classify_chart(icao, filename):
    """Classify a chart filename into (category, name, page)."""
    base = filename.replace(".pdf", "")
    prefix = icao + "-"
    if not base.startswith(prefix):
        return None, None, None
    rest = base[len(prefix):]

    chart_type = rest.split("-")[0]
    category = CHART_TYPE_MAP.get(chart_type)
    if category is None:
        return None, None, None

    name = rest.replace("-", " ")
    return category, name, base


def _head_ok(url):
    """Return True if a HEAD request to url returns HTTP 200."""
    req = urllib.request.Request(url, method="HEAD", headers={
        "User-Agent": "Mozilla/5.0 (compatible; MacheteCharts/1.0)"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def discover(cycle_date, work_dir):
    """Discover all Netherlands approach charts for the given AIRAC cycle."""
    base_url = _build_base_url(cycle_date)
    print(f"  Base URL: {base_url}")

    # Verify the base URL is reachable with a known chart
    test_url = base_url + "EHAM/EHAM-ADC.pdf"
    if not _head_ok(test_url):
        raise AIPUnavailableError(f"LVNL eAIP unreachable: {test_url}")

    airports = {}
    total_airports = len(AIRPORTS)

    for idx, (icao, apt_name) in enumerate(AIRPORTS.items(), 1):
        print(f"  [{idx}/{total_airports}] {icao} {apt_name}...", end="", flush=True)

        candidates = _candidate_filenames(icao)
        airport_url = base_url + f"{icao}/"

        plates = {"diagram": [], "approach": [], "departure": [], "star": []}
        found = 0

        for filename in candidates:
            url = airport_url + filename
            if _head_ok(url):
                category, name, page = _classify_chart(icao, filename)
                if category is not None:
                    plates[category].append({
                        "name": name,
                        "page": page,
                        "url": url,
                    })
                    found += 1

        print(f" {found} charts")

        has_plates = any(plates[c] for c in plates)
        if has_plates:
            airports[icao] = {
                "code": icao,
                "icao": icao,
                "name": apt_name,
                "volume": COUNTRY,
                "plates": plates,
            }

    print(f"  Done: {len(airports)} airports with charts")
    return {"country": "netherlands", "airports": airports}


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Netherlands LVNL: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    write_outputs(result, work_dir)
