#!/usr/bin/env python3
"""Generate the machete-charts .spb file by patching the VSR .spb structure."""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_spb import *

base = os.path.dirname(os.path.abspath(__file__))

# Load TextDecode
S = parse_textdecode_cs(os.path.join(base, 'TextDecode.Data.cs'))
K = build_K_table(S)

# Parse VSR .spb as template
data = read_spb(os.path.join(base, 'vs-radio-toolbar/InGamePanels/vs-radio-toolbar.spb'))
headers, tags, ds = parse_header(data)
tree, _ = walk(data, ds, len(data), tags, K)

# Patch with our values
# From VSR decode:
#   TEXT[1] = document type ('InGamePanels') - keep
#   LONG2[2] = version (1,0) - keep
#   TEXT[3] = filename
#   SET[4] contains:
#     TEXT[5] = panel id
#     TEXT[6] = panel name
#     TEXT[7] = url
#     INT[8] = resizeDirections (3=Both) - keep
#     FLOAT[9] = defaultWidth
#     FLOAT[10] = defaultHeight
#     FLOAT[11] = minWidth
#     FLOAT[12] = minHeight (or defaultTop/Right)
#     TEXT[13] = icon
#     BOOL[14] = buttonVisible - keep

patches = {
    3: 'machete-charts.spb',
    5: 'MACHETE_CHARTS_PANEL',
    6: 'Machete Charts',
    7: 'html_ui/InGamePanels/MacheteCharts/MacheteCharts.html',
    9: 50.0,   # defaultWidth
    10: 60.0,  # defaultHeight
    11: 20.0,  # minWidth
    12: 10.0,  # minHeight
    13: 'ICON_TOOLBAR_MACHETE_CHARTS',
}

patched_tree = patch(tree, patches)

# Rebuild
new_data = build_data(patched_tree, tags, S)
new_spb = build_spb(headers, tags, new_data)

# Write output
out_dir = os.path.join(base, 'machete-charts/InGamePanels')
os.makedirs(out_dir, exist_ok=True)
out_path = os.path.join(out_dir, 'machete-charts.spb')
with open(out_path, 'wb') as f:
    f.write(new_spb)
print(f"Generated {out_path} ({len(new_spb)} bytes)")

# Verify by re-parsing
print("\nVerification:")
data2 = read_spb(out_path)
h2, t2, ds2 = parse_header(data2)
tree2, _ = walk(data2, ds2, len(data2), t2, K)
