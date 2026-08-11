#!/usr/bin/env python3
"""
Finish the three VIC conversions: titles, and the screenshots.

import_vic.py handles the prose. This does the parts that need judgement —
each screenshot was inspected, and four of the six are pictures of text or
of a table, which belong in the page as text rather than as an image.

Usage:  python3 finish_vic.py <vic_out_dir> <review_dir>
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

TITLES = {
    "159783-2": "An unloved spinoff in a hated industry",
    "162278-2": "What Versant implies about the price of legacy TV",
    "163308-3": "SiriusXM after the satellites are paid for",
}

# Transcribed from the screenshots, verbatim.
WBD_VALUATION = (
    "The overall low to high latest 12 months adjusted EBITDA multiples observed for the "
    "selected diversified transactions were 7.9x to 16.5x, the overall low to high latest "
    "12 months adjusted EBITDA multiples observed for the selected U.S. linear transactions "
    "were 6.5x to 11.2x and the latest 12 months adjusted EBITDA multiples observed for the "
    "selected international linear transactions were 7.0x to 8.7x. Allen & Company and "
    "J.P. Morgan applied a selected range of latest 12 months adjusted EBITDA multiples "
    "derived from the selected transactions of 5.5x to 6.5x to the latest 12 months adjusted "
    "EBITDA (as of December 31, 2025) of Discovery Global, which indicated an approximate "
    "implied equity value reference range for Discovery Global of $4.63 to $6.86 per share."
)

WBD_LETTER = (
    "We are writing to inform you that Netflix has agreed to provide WBD a waiver of certain "
    "terms of the Netflix merger agreement to permit us, through February 23, to engage with "
    "PSKY to clarify your proposal, which we understand will include a WBD per share price "
    "higher than $31. We seek your best and final proposal. To be clear, our Board has not "
    "determined that your proposal is reasonably likely to result in a transaction that is "
    "superior to the Netflix merger. We continue to recommend and remain fully committed to "
    "our transaction with Netflix and have scheduled a special meeting of our shareholders "
    "on March 20, 2026 to vote on the Netflix merger agreement."
)

DG_VS_VSNT = """| | Discovery Global | Versant |
|---|---|---|
| Net debt / NTM leverage | ~$15bn / 3.9x | ~$2bn / 1.3x |
| Revenue growth, 2022–2024 CAGR | (7%) | (5%) |
| Revenue growth, 2022–2026E CAGR | (12%) | (6%) |
| EBITDA growth, 2022–2026E CAGR | (20%) | (10%) |
| Live news and sports, % of 2024 audience | 20%, before the loss of NBA rights | 62% |
| Average U.S. audience, 2024 | CNN 0.5mm | MS NOW 0.8mm |
| Growth outside pay TV | Limited | ~33% of revenue within 3–5 years |

*Versant's own comparison of the two businesses.*"""


def quote(text: str) -> str:
    return "\n".join("> " + line for line in [text])


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    images_out = out / "images"
    images_out.mkdir(exist_ok=True)

    # ---- STRZ: prose only -------------------------------------------
    strz = (src / "159783-2.md").read_text()

    # ---- VSNT: two text screenshots and one table screenshot --------
    vsnt = (src / "162278-2.md").read_text()
    vsnt = vsnt.replace(
        "WBD's Board thinks DG is worth between $4.63-$6.86 per share:",
        "WBD's Board thinks DG is worth between $4.63-$6.86 per share:\n\n" + quote(WBD_VALUATION))
    vsnt = vsnt.replace(
        "WBD's Board did not exercise their fiduciary out, but thinks the sum-of-the-parts is worth more than $31 per share:",
        "WBD's Board did not exercise their fiduciary out, but thinks the sum-of-the-parts is worth more than $31 per share:\n\n" + quote(WBD_LETTER))
    vsnt = vsnt.replace("## Discovery Global vs. Versant\n",
                        "## Discovery Global vs. Versant\n\n" + DG_VS_VSNT + "\n")
    # A heading VIC ran into the paragraph below it.
    vsnt = vsnt.replace(
        "The Transaction Comparable: Analysis of Netflix / Paramount / Warner Bros Discovery What follows",
        "## The Transaction Comparable\n\nWhat follows")

    # ---- SIRI: two genuine visuals ----------------------------------
    siri = (src / "163308-3.md").read_text()
    for old, new, anchor, caption in [
        ("163308-3-001-000.png", "siri-forward-multiples.png",
         "assuming a constant multiple.",
         "SiriusXM's forward EV/EBITDA, P/FCF and P/E since 2018. "
         "All three sit far below their medians of 12.2x, 15.3x and 19.9x."),
        ("163308-3-002-001.png", "siri-spectrum-valuation.png",
         "In total, the company controls 35MHz of contiguous spectrum in the 2GHz band.",
         "Valuing the 2GHz spectrum against the Echostar comparables."),
    ]:
        source = src / "images" / old
        if source.exists():
            shutil.copy2(source, images_out / new)
        if anchor in siri:
            # The anchor sits mid-paragraph, so the remainder has to start a
            # new paragraph — otherwise the caption welds onto the next
            # sentence and reads as part of it.
            siri = siri.replace(
                anchor + " ", f"{anchor}\n\n![[{new}]]\n\n*{caption}*\n\n", 1)
        else:
            print(f"  warn     anchor not found for {new}: {anchor!r}")

    # ---- common tidying ---------------------------------------------
    for stem, text in [("159783-2", strz), ("162278-2", vsnt), ("163308-3", siri)]:
        # Drop sections with no content — VIC's "Description" field holds the
        # writeup's own first heading, leaving an empty shell behind.
        text = re.sub(r"^## [^\n]+\n+(?=## )", "", text, flags=re.M)
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Retitle.
        text = re.sub(r"^# .*$", f"# {TITLES[stem]}", text, count=1, flags=re.M)
        target = out / f"{TITLES[stem]}.md"
        target.write_text(text.strip() + "\n", encoding="utf-8")
        print(f"  {target.name}  ({len(text.split()):,} words)")


if __name__ == "__main__":
    main()
