# Machete Charts

Free airport charts inside Microsoft Flight Simulator. View airport diagrams, instrument approaches, SIDs, and STARs without leaving the cockpit.

![Machete Charts](docs/screenshot.png)

## Supported Charts

Machete Charts gives you access to **3,900+ airports across 17 countries**, sourced from official government Aeronautical Information Publications (AIPs). Charts are updated every 28 days to match the AIRAC cycle.

- **Airport Diagrams** — Taxi layouts
- **Instrument Approaches** — ILS, RNAV, VOR, LOC, and visual approaches
- **Departures (SIDs)** — Standard instrument departure procedures
- **STARs** — Standard terminal arrival routes

### Countries

| Country | Airports | Source |
|---------|----------|--------|
| United States | 3,193 | FAA d-TPP |
| France | 132 | SIA eAIP |
| UK | 118 | NATS |
| Spain | 59 | ENAIRE |
| Germany | 58 | DFS BasicIFR |
| Norway | 52 | Avinor |
| Belgium | 50 | skeyes |
| Sweden | 45 | LFV |
| Denmark | 27 | Naviair |
| Finland | 24 | ANS Finland |
| Austria | 21 | Austro Control |
| Portugal | 19 | NAV Portugal |
| Netherlands | 17 | LVNL |
| Iceland | 14 | Isavia |
| Poland | 13 | PANSA |
| Czech Republic | 11 | ANS CR |
| Ireland | 9 | AirNav Ireland |

## Install

### Installer (Recommended)

Download **MacheteChartsSetup.exe** from the [latest release](https://github.com/tmhoule/MacheteCharts/releases) and run it. The installer auto-detects your MSFS Community folder.

### Manual Install

1. Download or clone this repo
2. Copy the `machete-charts` folder into your MSFS Community folder:
   - **MS Store 2024:** `%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community\`
   - **MS Store 2020:** `%LOCALAPPDATA%\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalCache\Packages\Community\`
   - **Steam:** `%APPDATA%\Microsoft Flight Simulator\Packages\Community\`
3. Restart MSFS

### PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

Or double-click `installer\install.bat`.

## How to Use

1. Open the toolbar at the top of the screen in MSFS
2. Click the **Machete Charts** icon
3. Type an airport code (e.g. `BOS`, `LFPG`, `EGLL`) or name and select from suggestions
4. Pick a chart category — Diagram, Approaches, Departures, or STARs
5. Select a plate to view it

### Navigation

- **Zoom:** Scroll wheel, pinch, or +/- buttons
- **Pan:** Click and drag
- **Quick zoom:** Double-click an area
- **Reset view:** Click **Fit**
- **New search:** Click **Clear**

### VR Tips

- Tap the search input to bring up the on-screen keyboard
- Use **^** / **v** to scroll suggestions, **Go** to select
- Use **A-** / **A+** to adjust text size (up to 300%)
- Your text size preference is saved between sessions

## Uninstall

Run `installer\uninstall.ps1` or delete the `machete-charts` folder from your MSFS Community folder.

## Requirements

- Microsoft Flight Simulator 2020 (v1.19.8+) or 2024
- Internet connection (charts are loaded on demand)

## Credits

Built by [hermes-tv.com](https://hermes-tv.com). US charts from the FAA's digital Terminal Procedures Publication (public domain). European charts from freely accessible government AIPs; copyright remains with the respective national aviation authorities.

## License

This project is provided as-is for flight simulation use.
