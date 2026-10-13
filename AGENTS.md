# Machete Charts — Agent Notes

## Environment

- NAS IP: `192.168.1.10` (no SSH username needed; uses SSH keys)
- `.env` file holds chart-update variables; script sources it automatically from `scripts/update-charts.sh`
- `.env` is in `.gitignore`

## Chart Updates

- Script: `scripts/update-charts.sh` (wrapper for country modules in `scripts/countries/`)
- Usage: `./scripts/update-charts.sh faa` or `--all`
- Charts follow the 28-day AIRAC cycle; current charts are stale (March 2026)
- Remote paths: `/volume1/web/MacheteCharts/charts` (images), `/volume1/web/MacheteCharts/charts.json`