#!/usr/bin/env python3
"""
Convert a Value Investors Club writeup PDF into a post for the vault.

VIC lays a writeup out as: company + ticker, date, author, a stats block,
then the prose under plain section headings, then a Messages thread of
member Q&A. Only the prose is wanted here.

Writes drafts to a review folder. Nothing goes near the vault until the
output has been read.

Usage:
    python3 import_vic.py <out_dir> <pdf> [<pdf> ...]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Everything from here down is the member Q&A thread.
STOP = "Messages"

# Every page carries a watermark naming the downloading member and their id,
# and a footer naming the site. Both are stripped: the pen name must never
# reach the site, and the writeups run there without attribution.
RE_WATERMARK = re.compile(r"Generated on\s+\d|\(\d{4,6}\)\s+Generated")
RE_FOOTER = re.compile(r"Page \d+ of \d+|valueinvestorsclub\.com|^Value Investors Club\b")

# Section names, taken from the writeups themselves. VIC does not reliably
# put a blank line before a heading, so an exact match is the only safe test:
# a heuristic swallowed most of them into the paragraph above.
KNOWN_SECTIONS = {
    "description", "background", "investment thesis", "company overview",
    "publicly traded peers", "separation transaction", "valuation", "risks",
    "catalyst", "catalysts", "appendix", "trigger events",
    "recent events and risks", "discovery global vs. versant",
    "conclusion", "summary",
}

# The catalyst list is written as bare lines with no bullet markers.
BULLET_SECTIONS = {"catalyst", "catalysts"}

RE_HEADER_DATE = re.compile(r"^([A-Z][a-z]+ \d{1,2}, \d{4})\s*-\s*\d")
RE_STATS = re.compile(
    r"^(Price|Shares Out|Market Cap|Net Debt|TEV|EPS|P/E|P/FCF|EBIT|TEV/EBIT)\b"
)


def pdf_pages(path: Path) -> list[str]:
    """Page text with the watermark and footer removed from each page."""
    text = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True
    ).stdout
    pages = []
    for page in text.split("\f"):
        kept = [
            line for line in page.split("\n")
            if not RE_WATERMARK.search(line) and not RE_FOOTER.search(line.strip())
        ]
        pages.append("\n".join(kept))
    return pages


def extract_images(path: Path, out_dir: Path, stem: str) -> dict[int, list[str]]:
    """Pull embedded images, grouped by the page they appear on."""
    listing = subprocess.run(
        ["pdfimages", "-list", str(path)], capture_output=True, text=True
    ).stdout
    pages: dict[int, list[str]] = {}
    rows = [r.split() for r in listing.split("\n")[2:] if r.strip()]
    if not rows:
        return pages
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / stem
    subprocess.run(["pdfimages", "-png", "-p", str(path), str(prefix)],
                   capture_output=True, text=True)
    for produced in sorted(out_dir.glob(f"{stem}-*.png")):
        # pdfimages -p names files <stem>-<page>-<index>.png
        parts = produced.stem.rsplit("-", 2)
        page = int(parts[1]) if len(parts) == 3 and parts[1].isdigit() else 1
        pages.setdefault(page, []).append(produced.name)
    return pages


def heading_of(line: str) -> str | None:
    """Return the canonical section name if this line is one, else None."""
    name = line.strip().rstrip(":").lower()
    return name if name in KNOWN_SECTIONS else None


def convert(pdf: Path, out_dir: Path) -> dict:
    stem = pdf.stem
    pages = pdf_pages(pdf)
    images = extract_images(pdf, out_dir / "images", stem)

    # -- header: company, ticker, date --------------------------------
    head = [l.strip() for l in pages[0].split("\n") if l.strip()][:8]
    company_line = head[0] if head else stem
    match = re.match(r"^(.*?)\s+([A-Z]{1,5})$", company_line)
    company, ticker = (match.group(1), match.group(2)) if match else (company_line, "")
    date = ""
    for line in head:
        found = RE_HEADER_DATE.match(line)
        if found:
            date = found.group(1)
            break

    # -- body ---------------------------------------------------------
    # A paragraph often runs across a page break. Join the pages without the
    # blank gap only when the previous page ends mid-sentence; otherwise the
    # break is real and two paragraphs would be welded together.
    trimmed = [p.strip("\n") for p in pages]
    whole = trimmed[0] if trimmed else ""
    for page in trimmed[1:]:
        tail = whole.rstrip().rsplit("\n", 1)[-1].strip()
        continues = bool(tail) and not tail.endswith((".", "?", "!", ":", '"', "”"))
        whole += ("\n" if continues else "\n\n") + page

    # A heading line always starts a new block, whether or not VIC left a
    # blank line above it.
    blocks, current = [], []
    for raw in whole.split("\n"):
        line = raw.strip()
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        if heading_of(line) or line == STOP:
            if current:
                blocks.append(current)
            blocks.append([line])
            current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    out: list[str] = []
    started = False
    section = ""
    for block in blocks:
        first = block[0].strip()
        if first == STOP:
            break
        name = heading_of(first)
        if not started:
            # Skip the company line, date, byline and the stats block.
            if name == "description":
                started = True
            else:
                continue
        if name:
            section = name
            out.append(f"## {first.rstrip(':')}")
            continue
        if RE_STATS.match(first) or first.startswith("by "):
            continue
        if section in BULLET_SECTIONS:
            items = [l if l.startswith(("-", "*")) else f"- {l}" for l in block]
            out.append("\n".join(items))       # a tight list, not a loose one
        else:
            out.append(" ".join(block).strip())

    body = "\n\n".join(out)
    # VIC requires a position disclosure. It reads as a stray paragraph inside
    # whatever section it landed in, so give it its own line at the foot.
    disclosure = re.search(
        r"(I (?:do not hold|hold) a position with the issuer.*?securities\.)",
        body, re.S)
    if disclosure:
        body = body.replace(disclosure.group(1), "").strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        body += f"\n\n## Disclosure\n\n{' '.join(disclosure.group(1).split())}"
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return {"company": company, "ticker": ticker, "date": date,
            "body": body, "images": images, "stem": stem}


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in sys.argv[2:]:
        pdf = Path(name)
        result = convert(pdf, out_dir)
        target = out_dir / f"{result['stem']}.md"
        header = [f"# {result['company']} ({result['ticker']})", ""]
        if result["date"]:
            header += [f"**Published:** {result['date']}", ""]
        header += ["---", ""]
        target.write_text("\n".join(header) + "\n" + result["body"] + "\n", encoding="utf-8")
        words = len(result["body"].split())
        pics = sum(len(v) for v in result["images"].values())
        print(f"  {target.name:<18} {result['ticker']:<5} {result['date']:<16} "
              f"{words:>6,} words  {pics} images")


if __name__ == "__main__":
    main()
