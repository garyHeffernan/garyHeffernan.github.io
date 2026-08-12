#!/usr/bin/env python3
"""
Email each new post to the Buttondown list.

This does by hand what Buttondown's RSS automation add-on does for $9/month.
It reads docs/feed.xml, works out which posts have not been emailed yet, and
creates one email per post through the Buttondown API. The API is free on
every plan; only the hosted automation is not.

The ledger of what has already gone out lives in sent.json, committed to the
repo. That is deliberate: the state is visible, diffable, and survives a
runner being thrown away. Nothing is inferred from timestamps, so a rebuild
that changes a date cannot re-send an old post.

Usage:
    python3 send_email.py --dry-run    # report what would send, send nothing
    python3 send_email.py              # send

Environment:
    BUTTONDOWN_API_KEY   required to send; ignored by --dry-run

First run:
    A new sent.json would treat all 16 posts as unsent and mail the archive.
    So the first run seeds the ledger instead of sending. Use --seed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FEED = ROOT / "docs" / "feed.xml"
LEDGER = ROOT / "sent.json"

API = "https://api.buttondown.com/v1/emails"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"

# Buttondown accepts "draft" or "about_to_send". Drafts are the safe default:
# Gary reads it and presses send. Set SEND_IMMEDIATELY to skip that step.
SEND_IMMEDIATELY = False


def die(message: str) -> None:
    print(f"  error    {message}", file=sys.stderr)
    sys.exit(1)


def read_feed() -> list[dict]:
    if not FEED.exists():
        die(f"no feed at {FEED} — run build.py first")
    root = ET.parse(FEED).getroot()
    items = []
    for item in root.findall("./channel/item"):
        link = item.findtext("link", "").strip()
        if not link:
            continue
        items.append(
            {
                "url": link,
                "title": item.findtext("title", "").strip(),
                "body": item.findtext(CONTENT, "") or item.findtext("description", ""),
            }
        )
    # The feed runs newest first. Send oldest first, so a backlog arrives in
    # the order it was written.
    return list(reversed(items))


def read_ledger() -> set[str]:
    if not LEDGER.exists():
        return set()
    return set(json.loads(LEDGER.read_text(encoding="utf-8")))


def write_ledger(urls: set[str]) -> None:
    LEDGER.write_text(
        json.dumps(sorted(urls), indent=2) + "\n", encoding="utf-8"
    )


def send(post: dict, key: str) -> None:
    """Create the email in Buttondown. Raises on any non-2xx reply."""
    payload = json.dumps(
        {
            "subject": post["title"],
            "body": post["body"] + footer(post["url"]),
            "status": "about_to_send" if SEND_IMMEDIATELY else "draft",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        API,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Token {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as reply:
            if reply.status not in (200, 201):
                die(f"buttondown replied {reply.status} for {post['title']!r}")
    except urllib.error.HTTPError as err:
        die(f"buttondown replied {err.code} for {post['title']!r}: {err.read().decode()[:300]}")
    except urllib.error.URLError as err:
        die(f"could not reach buttondown: {err.reason}")


def footer(url: str) -> str:
    """A link back to the canonical post. Buttondown appends the unsubscribe
    line itself, which is what keeps this compliant."""
    return f'\n<p><a href="{url}">Read this on the site</a></p>'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report, send nothing")
    parser.add_argument(
        "--seed",
        action="store_true",
        help="mark every current post as sent, without sending",
    )
    args = parser.parse_args()

    posts = read_feed()
    sent = read_ledger()
    pending = [p for p in posts if p["url"] not in sent]

    if args.seed:
        write_ledger({p["url"] for p in posts})
        print(f"  seeded   {len(posts)} posts marked as already sent")
        return

    if not pending:
        print("  nothing to send — every post in the feed has gone out")
        return

    for post in pending:
        print(f"  pending  {post['title']}")

    if args.dry_run:
        print(f"\n  {len(pending)} would send, nothing written")
        return

    key = os.environ.get("BUTTONDOWN_API_KEY", "").strip()
    if not key:
        # Not an error while the newsletter is still being set up. Failing here
        # would put a red cross on every publish for no reason. The posts stay
        # out of the ledger, so they still go the moment the key arrives.
        print("  skipped  BUTTONDOWN_API_KEY is not set — nothing emailed")
        return

    for post in pending:
        send(post, key)
        sent.add(post["url"])
        # Write after each one. If the third call fails, the first two stay
        # recorded and a re-run does not mail them twice.
        write_ledger(sent)
        state = "queued to send" if SEND_IMMEDIATELY else "created as a draft"
        print(f"  {state}: {post['title']}")

    print(f"\n  {len(pending)} emails {'sent' if SEND_IMMEDIATELY else 'drafted'}")


if __name__ == "__main__":
    main()
