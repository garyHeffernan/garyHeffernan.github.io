#!/usr/bin/env python3
"""
Download the five webfont files the site needs, once.

Google Fonts serves different files per browser. Asking with a Chrome
user-agent gets woff2, and only the latin subset is kept. Run this once;
build.py copies fonts/ into docs/ on every build.
"""

import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"

CSS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Roboto+Mono:ital,wght@0,400;0,700;1,400&display=swap"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

WANTED = {
    ("Roboto Mono", "400", "normal"): "roboto-mono-400",
    ("Roboto Mono", "700", "normal"): "roboto-mono-700",
    ("Roboto Mono", "400", "italic"): "roboto-mono-400i",
}


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    FONTS.mkdir(exist_ok=True)
    css = get(CSS_URL).decode("utf-8")

    blocks = re.findall(
        r"/\*\s*([\w\[\]-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", css, re.S
    )
    found = {}
    for subset, body in blocks:
        if subset != "latin":
            continue
        family = re.search(r"font-family:\s*'([^']+)'", body)
        weight = re.search(r"font-weight:\s*(\d+)", body)
        style = re.search(r"font-style:\s*(\w+)", body)
        url = re.search(r"url\((https://[^)]+\.woff2)\)", body)
        if not all((family, weight, style, url)):
            continue
        key = WANTED.get((family.group(1), weight.group(1), style.group(1)))
        if key:
            found[key] = url.group(1)

    missing = set(WANTED.values()) - set(found)
    if missing:
        print(f"  warn     no latin subset for: {', '.join(sorted(missing))}")

    total = 0
    for name, url in sorted(found.items()):
        data = get(url)
        (FONTS / f"{name}.woff2").write_bytes(data)
        total += len(data)
        print(f"  saved    fonts/{name}.woff2  ({len(data) / 1024:.0f} KB)")

    print(f"\n  {len(found)} files, {total / 1024:.0f} KB total")
    if not found:
        sys.exit("  error    nothing downloaded")


if __name__ == "__main__":
    main()
