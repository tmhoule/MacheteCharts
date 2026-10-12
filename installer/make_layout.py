"""Regenerate machete-charts/layout.json from the files on disk.

MSFS uses layout.json sizes and dates to load and cache package files. Stale
sizes or date 0 can make the sim serve old copies (e.g. a missing toolbar
icon or an outdated panel), so run this after every change and before packaging.

Usage: python installer/make_layout.py
"""
import json
import os

PACKAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "machete-charts")
SKIP = {"layout.json", "manifest.json", ".DS_Store"}

# Seconds between the Windows FILETIME epoch (1601) and the Unix epoch (1970)
EPOCH_DIFF = 11644473600


def filetime(path):
    return int((os.path.getmtime(path) + EPOCH_DIFF) * 10_000_000)


def main():
    content = []
    for root, dirs, files in os.walk(PACKAGE_DIR):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name in SKIP or name.startswith("."):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, PACKAGE_DIR).replace(os.sep, "/")
            content.append({"path": rel, "size": os.path.getsize(path), "date": filetime(path)})

    with open(os.path.join(PACKAGE_DIR, "layout.json"), "w", newline="\n") as f:
        json.dump({"content": content}, f, indent=2)
        f.write("\n")

    print(f"layout.json: {len(content)} files")


if __name__ == "__main__":
    main()
