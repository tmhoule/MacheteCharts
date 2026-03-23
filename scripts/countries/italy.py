"""Italy ENAV eAIP chart discovery module.

Requires free registration at https://www.enav.it/en/user/register
Set MACHETE_ENAV_USER and MACHETE_ENAV_PASS environment variables.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from base import current_airac_date, write_outputs

COUNTRY = "IT"


def discover(cycle_date, work_dir):
    """Discover Italian approach charts.

    Returns None if credentials are not configured.
    """
    user = os.environ.get("MACHETE_ENAV_USER")
    passwd = os.environ.get("MACHETE_ENAV_PASS")

    if not user or not passwd:
        print("  Skipping Italy -- no credentials configured.")
        print("  Set MACHETE_ENAV_USER and MACHETE_ENAV_PASS to enable.")
        print("  Register free at https://www.enav.it/en/user/register")
        return None

    # TODO: Implement authenticated ENAV eAIP scraping
    # The ENAV eAIP uses session-based auth with dynamic URLs.
    # Steps needed:
    #   1. POST login credentials to get session cookie
    #   2. Navigate to current eAIP
    #   3. Parse airport list (LI** ICAO codes)
    #   4. For each airport, parse chart links
    #   5. Download chart PDFs using session cookie
    print("  Italy module not yet implemented (auth scraping pending).")
    return None


if __name__ == "__main__":
    work_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/machete_charts"
    cycle_date = current_airac_date()
    print(f"Italy ENAV: AIRAC {cycle_date}")
    result = discover(cycle_date, work_dir)
    if result:
        write_outputs(result, work_dir)
    else:
        print("  No charts discovered.")
