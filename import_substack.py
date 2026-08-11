#!/usr/bin/env python3
"""
Import a Substack bulk export into the Obsidian vault.

Substack exports post bodies as HTML fragments with no title and no date —
both live in posts.csv — wrapped in a lot of subscribe-widget and icon-button
chrome. This turns each post into a note that build.py already understands:
an H1 title, a **Published:** line, and Obsidian image embeds.

One-off. Run it again only after a fresh export.

Usage:
    python3 import_substack.py --dry-run    # report, write nothing
    python3 import_substack.py              # write notes and images
"""

from __future__ import annotations

import csv
import html
import html.parser
import io
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import VAULT, slugify  # reuse the site's own slug rules

# ─── CONFIGURATION ────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
EXPORT = Path("/Users/garyheffernan/Documents/Safari Downloads/Substack Export 11Aug26")

PUBLISHED_DIR = VAULT / "ROUGH GROUND"
DRAFT_DIR = VAULT / "THOUGHTS IN PROGRESS"
IMAGE_DIR = VAULT / "Graphics" / "substack"
CACHE = ROOT / ".cache" / "substack-originals"

# Unpublished posts worth keeping, by slug. Everything else unpublished is
# Substack's own boilerplate and is skipped.
KEEP_DRAFTS = {
    "bubbles",
    "seeing-clearly",
    "pursuing-greatness",
    "what-are-financial-markets",
    "a-value-investor-i-thought-those",
    "distinction-description",
    "kings-ransom",
}

# The column is 650px, so 2x covers retina and nothing more.
MAX_WIDTH = 1300

PANDOC = shutil.which("pandoc")
SIPS = shutil.which("sips")

# Substack's own domains, across two renames of the publication.
SELF_HOSTS = ("orbitercapital.substack.com", "theroughground.substack.com",
              "garyheff.substack.com")
_HOSTS = "|".join(h.replace(".", r"\.") for h in SELF_HOSTS)
# Three shapes of link between his own posts:
#   <host>/p/<slug>                       the ordinary one
#   open.substack.com/pub/<pub>/p/<slug>  the share-sheet one, with tracking
#   <host>/i/<post_id>/<anchor>           a deep link to a heading
RE_SELF_LINK = re.compile(rf"https?://(?:{_HOSTS})/p/([a-z0-9\-]+)(\?[^\s)\]]*)?")
RE_SELF_OPEN = re.compile(
    r"https?://open\.substack\.com/pub/[a-z0-9\-]+/p/([a-z0-9\-]+)(\?[^\s)\]]*)?"
)
RE_SELF_DEEP = re.compile(rf"https?://(?:{_HOSTS})/i/(\d+)/([a-z0-9\-]+)")

# Subtrees dropped whole: subscribe forms, CTA buttons, and the icon chrome
# that would otherwise become 63 stray SVG buttons in the markdown.
DROP_CLASSES = {
    "subscription-widget-wrap-editor",
    "button-wrapper",
    "captioned-button-wrap",
    "image-link-expand",
}
DROP_CLASS_PREFIXES = ("pencraft",)
DROP_COMPONENTS = {
    "SubscribeWidgetToDOM",
    "ButtonCreateButton",
    "CaptionedButtonToDOM",
}

EMBED_HOSTS = {
    "youtube-nocookie.com": "YouTube",
    "youtube.com": "YouTube",
    "player.vimeo.com": "Vimeo",
    "open.spotify.com": "Spotify",
    "w.soundcloud.com": "SoundCloud",
}

VOID = {"img", "br", "hr", "input", "source", "meta", "link", "col"}

TOKEN_IMAGE = "%%RG-IMAGE:{}%%"
TOKEN_CAPTION = "%%RG-CAPTION:{}%%"
RE_TOKEN_IMAGE = re.compile(r"%%RG-IMAGE:(.+?)%%")
RE_TOKEN_CAPTION = re.compile(r"%%RG-CAPTION:(.+?)%%")


# ─── MODEL ────────────────────────────────────────────────────────────────


@dataclass
class Row:
    post_id: str
    slug: str
    date: datetime | None
    published: bool
    title: str
    subtitle: str
    html_path: Path
    images: list[dict] = field(default_factory=list)
    body: str = ""
    filename: str = ""
    target: Path | None = None


def die(message: str) -> None:
    print(f"  error    {message}", file=sys.stderr)
    sys.exit(1)


# ─── HTML CLEANER ─────────────────────────────────────────────────────────


class Cleaner(html.parser.HTMLParser):
    """Walk a Substack fragment, drop the chrome, and emit clean HTML.

    Images and captions become sentinel tokens, because pandoc would rewrite
    or escape the paths we want to control ourselves.
    """

    def __init__(self, slug: str):
        super().__init__(convert_charrefs=True)
        self.slug = slug
        self.out: list[str] = []
        self.images: list[dict] = []
        self.drop_depth = 0          # >0 while inside a dropped subtree
        self.drop_stack: list[int] = []
        self.depth = 0
        self.in_heading = False
        self.caption_depth = 0
        self.footnote_depth = 0
        self.footnotes: list[str] = []
        # <a class="image-link"> only links the image to its CDN original.
        # Unwrap it — dropping the subtree would take the <img> with it.
        self.unwrapped_a: set[int] = set()

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _attr(attrs, name):
        for key, value in attrs:
            if key == name:
                return value or ""
        return ""

    def _should_drop(self, tag, attrs) -> bool:
        classes = self._attr(attrs, "class").split()
        if any(c in DROP_CLASSES for c in classes):
            return True
        if any(c.startswith(DROP_CLASS_PREFIXES) for c in classes):
            return True
        if self._attr(attrs, "data-component-name") in DROP_COMPONENTS:
            return True
        return False

    def emit(self, text: str) -> None:
        if not self.drop_depth:
            self.out.append(text)

    # -- parser callbacks ------------------------------------------------

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.depth += 1
        classes = self._attr(attrs, "class").split()
        component = self._attr(attrs, "data-component-name")

        if self.drop_depth:
            if tag not in VOID:
                pass  # stay inside the dropped subtree
            return

        if self._should_drop(tag, attrs):
            if tag in VOID:
                return
            self.drop_depth = 1
            self.drop_stack.append(self.depth)
            return

        # Images: capture the direct S3 src, emit a token.
        if tag == "img":
            src = self._attr(attrs, "src")
            if not src:
                return
            index = len(self.images) + 1
            name = f"{self.slug}-{index:02d}"
            # The 2022-era S3 bucket returns 403 on direct access, so keep the
            # widest signed CDN variant from srcset as a fallback.
            fallback = ""
            widths = re.findall(r"(https://substackcdn\.com/\S+?)\s+(\d+)w",
                                self._attr(attrs, "srcset"))
            if widths:
                fallback = max(widths, key=lambda pair: int(pair[1]))[0]
            self.images.append({"url": src, "fallback": fallback,
                                "name": name, "index": index})
            self.emit(f"<p>{TOKEN_IMAGE.format(name)}</p>")
            return

        if tag == "source":            # <picture> alternates, always redundant
            return

        if tag == "figcaption" and "image-caption" in classes:
            self.caption_depth = self.depth
            self.emit("<p>%%RG-CAPSTART%%")
            return

        # Embeds: reduce to a link on its own line.
        if tag == "iframe":
            src = self._attr(attrs, "src")
            label = next((n for h, n in EMBED_HOSTS.items() if h in src), "Embedded media")
            if src:
                self.emit(f'<p><a href="{html.escape(src, quote=True)}">{label}</a></p>')
            return

        # Substack cross-post card: keep only the link.
        if component == "EmbeddedPostToDOM":
            data = self._attr(attrs, "data-attrs")
            url = ""
            try:
                url = json.loads(html.unescape(data)).get("canonical_url", "")
            except Exception:
                pass
            if url:
                self.emit(f'<p><a href="{html.escape(url, quote=True)}">{html.escape(url)}</a></p>')
            self.drop_depth = 1
            self.drop_stack.append(self.depth)
            return

        # Tweet: text lives only in the escaped JSON blob.
        if component == "Twitter2ToDOM":
            data = self._attr(attrs, "data-attrs")
            try:
                blob = json.loads(html.unescape(data))
                url, text = blob.get("url", ""), blob.get("full_text", "")
                if url:
                    self.emit(
                        f"<blockquote><p>{html.escape(text)}</p>"
                        f'<p><a href="{html.escape(url, quote=True)}">{html.escape(url)}</a></p></blockquote>'
                    )
            except Exception:
                pass
            return

        # Footnote definition and anchor.
        if "footnote" in classes and tag == "div":
            self.footnote_depth = self.depth
            self.emit("<p>%%RG-FN-DEF%%")
            return
        if tag == "a" and "footnote-anchor" in classes:
            self.emit("%%RG-FN-REF%%")
            self.drop_depth = 1
            self.drop_stack.append(self.depth)
            return
        if tag == "a" and "footnote-number" in classes:
            self.drop_depth = 1
            self.drop_stack.append(self.depth)
            return

        if tag in {"picture", "figure", "span", "div", "button", "svg", "form",
                   "input", "polyline", "line", "path", "g"}:
            # Structural wrappers carry no meaning once the chrome is gone.
            return

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.in_heading = True

        attr_text = ""
        if tag == "a":
            if "image-link" in classes:
                self.unwrapped_a.add(self.depth)
                return
            href = self._attr(attrs, "href")
            if href:
                attr_text = f' href="{html.escape(href, quote=True)}"'
        self.emit(f"<{tag}{attr_text}>")

    def handle_endtag(self, tag):
        if self.drop_depth and self.drop_stack and self.depth == self.drop_stack[-1]:
            self.drop_stack.pop()
            self.drop_depth = len(self.drop_stack)
            self.depth -= 1
            return

        if self.caption_depth and self.depth == self.caption_depth and tag == "figcaption":
            self.caption_depth = 0
            self.emit("%%RG-CAPEND%%</p>")
            self.depth -= 1
            return

        if self.footnote_depth and self.depth == self.footnote_depth and tag == "div":
            self.footnote_depth = 0
            self.emit("</p>")
            self.depth -= 1
            return

        if tag not in VOID:
            self.depth -= 1

        if tag in {"picture", "figure", "span", "div", "button", "svg", "form",
                   "input", "polyline", "line", "path", "g", "source", "figcaption"}:
            return
        if tag == "a" and self.depth in self.unwrapped_a:
            self.unwrapped_a.discard(self.depth)
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.in_heading = False
        self.emit(f"</{tag}>")

    def handle_data(self, data):
        if self.drop_depth:
            return
        # Substack wraps heading text in <strong>; the heading is already bold.
        self.emit(html.escape(data))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)


def clean_fragment(raw: str, slug: str) -> tuple[str, list[dict]]:
    # <strong> inside a heading is redundant and pandoc turns it into ** ** .
    raw = re.sub(r"(<h[1-6][^>]*>)\s*<strong>(.*?)</strong>\s*(</h[1-6]>)",
                 r"\1\2\3", raw, flags=re.S)
    # Substack wraps every list item's content in a paragraph.
    raw = re.sub(r"<li>\s*<p>(.*?)</p>\s*</li>", r"<li>\1</li>", raw, flags=re.S)
    cleaner = Cleaner(slug)
    cleaner.feed(raw)
    cleaner.close()
    return "".join(cleaner.out), cleaner.images


# ─── IMAGES ───────────────────────────────────────────────────────────────


def sniff_extension(data: bytes, url: str) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:3] == b"GIF":
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tiff"
    suffix = Path(url.split("?")[0]).suffix.lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff"} else ".png"


def download(url: str, name: str, fallback: str = "") -> Path | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for existing in CACHE.glob(name + ".*"):
        return existing
    last = None
    for candidate in (url, fallback):
        if not candidate:
            continue
        try:
            request = urllib.request.Request(
                candidate, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            path = CACHE / (name + sniff_extension(data, candidate))
            path.write_bytes(data)
            return path
        except Exception as error:
            last = error
    print(f"  warn     download failed {name}: {last}")
    return None


def downscale(src: Path, dest: Path) -> tuple[int, int]:
    """Copy to dest, resampling to MAX_WIDTH when wider. Returns (before, after)."""
    from build import image_size

    data = src.read_bytes()
    size = image_size(data)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not size or size[0] <= MAX_WIDTH or not SIPS or src.suffix == ".gif":
        dest.write_bytes(data)
        return len(data), len(data)
    result = subprocess.run(
        [SIPS, "--resampleWidth", str(MAX_WIDTH), str(src), "--out", str(dest)],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not dest.exists():
        dest.write_bytes(data)
        return len(data), len(data)
    return len(data), dest.stat().st_size


# ─── CONVERSION ───────────────────────────────────────────────────────────


def pandoc_html_to_md(markup: str) -> str:
    result = subprocess.run(
        [PANDOC, "--from", "html", "--to", "gfm", "--wrap=none"],
        input=markup, capture_output=True, text=True,
    )
    if result.returncode != 0:
        die(f"pandoc failed: {result.stderr.strip()}")
    return result.stdout.strip()


def tokens_to_obsidian(markdown: str, images: list[dict]) -> str:
    by_name = {i["name"]: i for i in images}

    def image(match: re.Match) -> str:
        entry = by_name.get(match.group(1))
        if entry and entry.get("file"):
            return f"![[{entry['file']}]]"
        # Never let a failed download silently delete an image from the post.
        url = entry.get("url", "") if entry else ""
        return f"*[image failed to download: {url}]*"

    markdown = RE_TOKEN_IMAGE.sub(image, markdown)
    # Captions: the cleaner marked them, turn them into the italic convention.
    markdown = re.sub(r"%%RG-CAPSTART%%\s*(.*?)\s*%%RG-CAPEND%%",
                      lambda m: f"*{m.group(1).strip()}*" if m.group(1).strip() else "",
                      markdown, flags=re.S)
    markdown = markdown.replace("%%RG-FN-REF%%", "[^1]")
    markdown = re.sub(r"%%RG-FN-DEF%%\s*", "[^1]: ", markdown)
    markdown = unescape(markdown)
    # Substack's editor leaves non-breaking spaces everywhere. A trailing one
    # in a heading gives pandoc a heading id with a stray hyphen, which breaks
    # the deep links between posts.
    markdown = markdown.replace(" ", " ")
    markdown = re.sub(r"^(#{1,6} .*?)[ \t]+$", r"\1", markdown, flags=re.M)
    markdown = normalise_headings(markdown)
    # Collapse the blank lines the removals leave behind.
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    return markdown.strip()


RE_HEADING = re.compile(r"^(#{2,6})\s+(.*)$", re.M)


def normalise_headings(markdown: str) -> str:
    """Promote each post's top heading level to h2, keeping the hierarchy.

    Substack's editor emits h2, h3 or h4 for what the author meant as a
    section, inconsistently between posts. The site styles h2 as a numbered
    divider, so a post whose sections are h3 would show none.

    A heading that is really an epigraph — wholly italic, or opening with a
    quotation mark — becomes a blockquote instead. An uppercase numbered
    divider is the wrong shape for a pull quote.
    """
    levels = [len(m.group(1)) for m in RE_HEADING.finditer(markdown)]
    if not levels:
        return markdown
    shift = min(levels) - 2

    def rewrite(match: re.Match) -> str:
        level, text = len(match.group(1)), match.group(2).strip()
        bare = text.strip("*_ ")
        if level - shift == 2 and (bare.startswith(("“", '"', "‘")) or
                                   re.fullmatch(r"[*_].+[*_]", text)):
            # Drop the emphasis markers entirely. They are decorative on a
            # pull quote, the stylesheet italicises blockquotes anyway, and
            # keeping them leaves an unbalanced "*" when the quote mark comes
            # first: “*You're looking for a mispriced gamble…
            return "> " + re.sub(r"[*_]", "", bare).strip()
        return "#" * max(2, level - shift) + " " + text

    return RE_HEADING.sub(rewrite, markdown)


RE_ESCAPE = re.compile(r"\\([#\->])")


def unescape(markdown: str) -> str:
    """Drop pandoc's defensive backslashes where they cannot matter.

    "$" never has meaning here — there is no math, only tickers — so every
    one goes. "#", "-" and ">" only mean something at the start of a line,
    so those are unescaped mid-line and left alone at the margin.
    """
    markdown = markdown.replace(r"\$", "$")
    lines = []
    for line in markdown.split("\n"):
        indent = len(line) - len(line.lstrip())
        head, tail = line[:indent + 2], line[indent + 2:]
        lines.append(head + RE_ESCAPE.sub(r"\1", tail))
    return "\n".join(lines)


def sanitize_filename(title: str) -> str:
    # Parentheses are deleted rather than replaced, because Gary writes them
    # inside words — "Liquid(ia) Gold" should slug to liquidia-gold, not
    # liquid-ia-gold.
    name = re.sub(r"[$?:/\\#^\[\]|*<>\"()]", "", title)
    name = name.replace("“", "").replace("”", "").replace("’", "'")
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120]


# ─── MAIN ─────────────────────────────────────────────────────────────────


def read_rows() -> list[Row]:
    index = EXPORT / "posts.csv"
    if not index.exists():
        die(f"posts.csv not found at {index}")
    rows: list[Row] = []
    with index.open(encoding="utf-8-sig", newline="") as handle:
        for record in csv.DictReader(handle):
            post_id = record["post_id"]
            slug = post_id.split(".", 1)[1] if "." in post_id else post_id
            stamp = (record.get("post_date") or "").strip()
            date = None
            if stamp:
                date = datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
            path = EXPORT / "posts" / f"{post_id}.html"
            rows.append(Row(
                post_id=post_id,
                slug=slug,
                date=date,
                published=(record.get("is_published", "").strip().lower() == "true"),
                title=(record.get("title") or "").strip(),
                subtitle=(record.get("subtitle") or "").strip(),
                html_path=path,
            ))
    return rows


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    if not PANDOC:
        die("pandoc not found")
    if not EXPORT.is_dir():
        die(f"export folder not found: {EXPORT}")

    rows = read_rows()
    published = [r for r in rows if r.published]
    drafts = [r for r in rows if not r.published and r.slug in KEEP_DRAFTS]
    skipped = [r for r in rows if not r.published and r.slug not in KEEP_DRAFTS]

    print(f"  export   {EXPORT}")
    print(f"  {len(rows)} rows: {len(published)} published, "
          f"{len(drafts)} drafts kept, {len(skipped)} skipped")

    # Titles first, so self-links can be rewritten to final URLs.
    for row in published + drafts:
        title = row.title or row.slug.replace("-", " ").title()
        row.title = title
        row.filename = sanitize_filename(title)
        row.target = (PUBLISHED_DIR if row.published else DRAFT_DIR) / f"{row.filename}.md"
    slug_to_url = {r.slug: f"/{slugify(r.filename)}/" for r in published}
    id_to_url = {r.post_id.split(".", 1)[0]: f"/{slugify(r.filename)}/" for r in published}

    seen: dict[Path, str] = {}
    problems = 0
    total_before = total_after = 0
    image_count = 0

    for row in published + drafts:
        if not row.html_path.exists():
            print(f"  warn     missing HTML for {row.slug}")
            problems += 1
            continue
        if row.target in seen:
            print(f"  error    filename collision: {row.target.name} "
                  f"({row.slug} and {seen[row.target]})")
            problems += 1
            continue
        seen[row.target] = row.slug
        if row.target.exists() and not force:
            print(f"  skip     exists already: {row.target.name}")
            continue

        markup, images = clean_fragment(row.html_path.read_text(encoding="utf-8"), row.slug)

        for entry in images:
            image_count += 1
            if dry_run:
                entry["file"] = f"{entry['name']}.png"
                continue
            original = download(entry["url"], entry["name"], entry.get("fallback", ""))
            if original is None:
                problems += 1
                continue
            destination = IMAGE_DIR / (entry["name"] + original.suffix)
            before, after = downscale(original, destination)
            total_before += before
            total_after += after
            entry["file"] = destination.name

        body = tokens_to_obsidian(pandoc_html_to_md(markup), images)

        # Rewrite links between his own posts to local URLs.
        def relink(match: re.Match) -> str:
            target = slug_to_url.get(match.group(1))
            if target is None:
                print(f"  warn     unresolved self-link /p/{match.group(1)} in {row.slug}")
                return match.group(0)
            return target      # tracking query string is dropped with it

        def relink_deep(match: re.Match) -> str:
            target = id_to_url.get(match.group(1))
            if target is None:
                print(f"  warn     unresolved deep link /i/{match.group(1)} in {row.slug}")
                return match.group(0)
            return f"{target}#{match.group(2)}"

        body = RE_SELF_LINK.sub(relink, body)
        body = RE_SELF_OPEN.sub(relink, body)
        body = RE_SELF_DEEP.sub(relink_deep, body)

        header = [f"# {row.title}", ""]
        if row.published and row.date:
            header += [f"**Published:** {row.date.strftime('%B %-d, %Y')}", ""]
        if row.subtitle:
            header += [f"**Subtitle:** {row.subtitle}", ""]
        header += ["---", ""]
        note = "\n".join(header) + body + "\n"

        words = len(re.sub(r"[#*`\[\]!]", " ", body).split())
        where = "ROUGH GROUND" if row.published else "THOUGHTS IN PROGRESS"
        print(f"  {'would write' if dry_run else 'wrote      '} {where}/{row.target.name}"
              f"  ({words:,} words, {len(images)} images)")

        if not dry_run:
            row.target.parent.mkdir(parents=True, exist_ok=True)
            row.target.write_text(note, encoding="utf-8")

    print()
    if dry_run:
        print(f"  dry run — nothing written. {image_count} images would download.")
    else:
        saved = (total_before - total_after) / 1024 / 1024
        print(f"  images   {image_count} downloaded → {IMAGE_DIR}")
        if total_before:
            print(f"           {total_before/1024/1024:.1f} MB → {total_after/1024/1024:.1f} MB "
                  f"({saved:.1f} MB saved by downscaling to {MAX_WIDTH}px)")
    if problems:
        print(f"  {problems} problem(s) reported above")


if __name__ == "__main__":
    main()
