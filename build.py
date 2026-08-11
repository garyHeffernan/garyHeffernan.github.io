#!/usr/bin/env python3
"""
Build "Investing on Rough Ground" from the Obsidian vault.

Reads markdown straight out of the vault, converts it with pandoc, and writes
a static site into docs/. No frontmatter required: the title is the H1 and the
date comes from the "**Published:** June 15, 2023" line.

Usage:
    python3 build.py            # build into docs/
    python3 build.py --check    # parse and report, write nothing
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ─── CONFIGURATION ────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs"

VAULT = Path("/Users/garyheffernan/claudecode/Writing")

# Add more folders here to widen what gets published, e.g.
#   VAULT / "THOUGHTS IN PROGRESS" / "Completed"
SOURCES = [VAULT / "ROUGH GROUND"]

# The about page. It sits inside a posts folder, so collect() skips it by
# path — it is a page, not a post, and needs no **Published:** line.
ABOUT_SOURCE = VAULT / "ROUGH GROUND" / "About.md"

SITE = {
    "title": "Investing on Rough Ground",
    "author": "Gary Heffernan",
    "url": "https://garyheffernan.github.io",
    "description": "Notes on markets from the rough ground.",
    "lang": "en",
}

# The terminal box at the top of every page.
MASTHEAD = [
    "&gt; Hello",
    "&gt; My name is Gary",
    "&gt; Notes on markets from the rough ground",
]

# Files never published, whatever folder they sit in.
EXCLUDE = {"CLAUDE.md", "GEMINI.md", "README.md", "Scratch.md", "Formatter.md"}

PANDOC = shutil.which("pandoc")
MD_FORMAT = "gfm+smart+footnotes"

FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='7' fill='%23353535'/%3E"
    "%3Ctext x='16' y='23' font-family='monospace' font-size='20' "
    "font-weight='700' fill='%23CAD2D4' text-anchor='middle'%3E%3E%3C/text%3E%3C/svg%3E"
)


# ─── MODEL ────────────────────────────────────────────────────────────────


@dataclass
class Post:
    source: Path
    title: str
    date: datetime
    slug: str
    subtitle: str = ""
    lede_md: str = ""
    body_md: str = ""
    lede_html: str = field(default="", repr=False)
    body_html: str = field(default="", repr=False)
    excerpt: str = ""

    @property
    def url(self) -> str:
        return f"/{self.slug}/"

    @property
    def date_long(self) -> str:
        # "Thu, Jun 15, 2023" — matches the terminal-readout feel
        return self.date.strftime("%a, %b %-d, %Y")

    @property
    def date_short(self) -> str:
        return self.date.strftime("%b %-d, %Y")

    @property
    def rfc822(self) -> str:
        return self.date.replace(tzinfo=timezone.utc).strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )


# ─── HELPERS ──────────────────────────────────────────────────────────────


def die(message: str) -> None:
    print(f"  error    {message}", file=sys.stderr)
    sys.exit(1)


def pandoc(text: str, to: str = "html5") -> str:
    """Convert markdown with pandoc. Returns an empty string for empty input."""
    if not text.strip():
        return ""
    result = subprocess.run(
        [PANDOC, "--from", MD_FORMAT, "--to", to, "--wrap=none"],
        input=text,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        die(f"pandoc failed: {result.stderr.strip()}")
    return result.stdout.strip()


def slugify(stem: str, limit: int = 60) -> str:
    """Build a URL slug from a filename stem, which Gary controls by renaming.

    Pass limit=0 for the untrimmed slug. Trimming is what makes two titles
    collide when they differ only after the cut — "… Discovery" and
    "… Discovery Part 2" — so callers fall back to the full form.
    """
    s = stem.lower()
    s = s.replace("&", " and ")
    # Drop apostrophes rather than break on them: "Paramount's" should slug
    # to paramounts, not paramount-s.
    s = re.sub(r"['’‘]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if limit and len(s) > limit:  # trim on a word boundary
        s = s[:limit].rsplit("-", 1)[0]
    return s


def load_slugs() -> dict:
    path = ROOT / "slugs.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_slugs(slugs: dict) -> None:
    (ROOT / "slugs.json").write_text(
        json.dumps(slugs, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def tidy(markup: str) -> str:
    """Clean up pandoc output for this stylesheet."""
    # Wide tables scroll inside their own box, never the page.
    markup = markup.replace("<table>", '<div class="table-wrap"><table>')
    markup = markup.replace("</table>", "</table></div>")

    # Gary separates sections with "---" before each heading. The headings
    # already carry a rule, so the <hr> would double it.
    markup = re.sub(r"<hr\s*/?>\s*(?=<h[23])", "", markup)
    markup = re.sub(r"<hr\s*/?>\s*$", "", markup.strip())
    return markup.strip()


def esc(text: str) -> str:
    return html.escape(text, quote=True)


# ─── IMAGES ───────────────────────────────────────────────────────────────
#
# Obsidian writes embeds as ![[bare filename.png]] with no path, so every
# reference is resolved by searching the vault. Assets are copied into
# docs/images/ under a content-hashed name, which lets browsers cache them
# forever and makes an edited image a new file rather than a stale one.

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif", ".heic"}

# Converted for the web only. The vault keeps its originals, so nothing in
# Obsidian changes and the conversion stays reversible.
WEBP = shutil.which("cwebp")
WEBP_QUALITY = "82"
WEBP_FROM = {".png", ".jpg", ".jpeg"}   # not .gif — that would drop animation

# Filled during rendering, written to disk at the end of the build.
ASSETS: dict[str, bytes] = {}
# Intrinsic pixel size per asset, measured before any conversion.
ASSET_SIZES: dict[str, tuple[int, int]] = {}

RE_EMBED = re.compile(r"!\[\[([^\]|]+?)(?:\|([^\]]*))?\]\]")
# Obsidian writes unencoded spaces in paths, so the target may contain them.
RE_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\"<>]+?)>?(?:\s+\"[^\"]*\")?\s*\)")
# An italic line on its own directly under an image. Match only horizontal
# whitespace at the end, or the blank line separating the next block is eaten
# and pandoc folds that paragraph into the raw HTML.
RE_CAPTION = re.compile(
    r"(<img [^>]+>)[ \t]*\n[ \t]*\n[ \t]*\*([^*\n][^\n]*?)\*[ \t]*(?=\n|$)"
)

_vault_files: dict[str, Path] | None = None


def vault_index() -> dict[str, Path]:
    """Map every lowercased filename in the vault to its path, built once."""
    global _vault_files
    if _vault_files is None:
        _vault_files = {}
        for path in VAULT.rglob("*"):
            if path.is_file() and not any(p.startswith(".") for p in path.parts):
                _vault_files.setdefault(path.name.lower(), path)
    return _vault_files


def image_size(data: bytes) -> tuple[int, int] | None:
    """Read intrinsic pixel size from the file header. No dependencies."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
            return w, h
        if data[:3] == b"GIF":
            return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X":
                w = int.from_bytes(data[24:27], "little") + 1
                h = int.from_bytes(data[27:30], "little") + 1
                return w, h
            if chunk == b"VP8 ":
                return (
                    int.from_bytes(data[26:28], "little") & 0x3FFF,
                    int.from_bytes(data[28:30], "little") & 0x3FFF,
                )
        if data[:2] == b"\xff\xd8":  # JPEG: walk the segments to a SOF marker
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    h = int.from_bytes(data[i + 5 : i + 7], "big")
                    w = int.from_bytes(data[i + 7 : i + 9], "big")
                    return w, h
                i += 2 + int.from_bytes(data[i + 2 : i + 4], "big")
    except Exception:
        pass
    return None


def convert_heic(src: Path) -> Path | None:
    """HEIC does not render on the web. macOS ships sips, which converts it."""
    sips = shutil.which("sips")
    if not sips:
        print(f"  warn     cannot convert {src.name} — sips not found")
        return None
    cache = ROOT / ".cache" / "converted"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / (src.stem + ".jpg")
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        result = subprocess.run(
            [sips, "-s", "format", "jpeg", str(src), "--out", str(out)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"  warn     sips failed on {src.name}")
            return None
    return out


def fetch_remote(url: str) -> Path | None:
    """Download a hotlinked image once and keep it. CDN links rot."""
    import urllib.request

    cache = ROOT / ".cache" / "remote"
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode()).hexdigest()[:12]
    for existing in cache.glob(key + ".*"):
        return existing
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
            kind = response.headers.get("content-type", "").split(";")[0]
    except Exception as error:
        print(f"  warn     could not fetch {url[:60]}… — {error}")
        return None
    ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }.get(kind, ".png")
    out = cache / (key + ext)
    out.write_bytes(data)
    print(f"  fetched  {url[:52]}… → {out.name} ({len(data) / 1024:.0f} KB)")
    return out


def to_webp(data: bytes, digest: str) -> bytes | None:
    """Convert to WebP, cached by content hash so rebuilds stay fast."""
    if not WEBP:
        return None
    cache = ROOT / ".cache" / "webp"
    cache.mkdir(parents=True, exist_ok=True)
    hit = cache / f"{digest}.webp"
    if hit.exists():
        return hit.read_bytes()
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(data)
        source = handle.name
    try:
        result = subprocess.run(
            [WEBP, "-quiet", "-q", WEBP_QUALITY, source, "-o", str(hit)],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not hit.exists():
            return None
        return hit.read_bytes()
    finally:
        Path(source).unlink(missing_ok=True)


def register_asset(src: Path, folder: str = "images") -> str | None:
    """Stage a file for docs/<folder>/ and return the URL it will live at."""
    if src.suffix.lower() == ".heic":
        converted = convert_heic(src)
        if converted is None:
            return None
        src = converted
    try:
        data = src.read_bytes()
    except OSError as error:
        print(f"  warn     unreadable asset {src.name} — {error}")
        return None

    digest = hashlib.sha1(data).hexdigest()[:8]
    suffix = src.suffix.lower()
    size = image_size(data)      # measure before converting; WebP keeps it

    if folder == "images" and suffix in WEBP_FROM:
        converted = to_webp(data, digest)
        # Keep whichever is smaller. WebP loses on some small flat PNGs.
        if converted and len(converted) < len(data):
            data, suffix = converted, ".webp"

    name = f"{slugify(src.stem)}-{digest}{suffix}"
    web = f"{folder}/{name}"
    ASSETS[web] = data
    if size:
        ASSET_SIZES[web] = size
    return f"/{web}"


def find_in_vault(target: str, note: Path) -> Path | None:
    """Resolve an Obsidian target: beside the note, from the vault root, or
    anywhere in the vault by filename — which is how bare embeds work."""
    target = target.split("#")[0].strip()
    if not target:
        return None
    for candidate in (note.parent / target, VAULT / target):
        if candidate.is_file():
            return candidate
    return vault_index().get(Path(target).name.lower())


def img_tag(web: str, alt: str, size: tuple[int, int] | None, width_hint: str = "") -> str:
    attrs = f'src="{web}" alt="{esc(alt)}" loading="lazy" decoding="async"'
    if size:
        attrs += f' width="{size[0]}" height="{size[1]}"'
    if width_hint.isdigit():
        attrs += f' style="max-width:{width_hint}px"'
    return f"<img {attrs}>"


def resolve_assets(markdown: str, note: Path) -> str:
    """Rewrite every image reference to a local, cached, sized <img> tag."""

    def from_embed(match: re.Match) -> str:
        target, option = match.group(1).strip(), (match.group(2) or "").strip()
        path = find_in_vault(target, note)
        if path is None:
            print(f"  warn     missing embed [[{target}]] in {note.name}")
            return f"*[missing: {target}]*"
        if path.suffix.lower() not in IMAGE_EXT:
            # Not an image — a PDF or similar. Offer it as a download.
            web = register_asset(path, folder="files")
            return f"[{path.name}]({web})" if web else f"*[missing: {target}]*"
        web = register_asset(path)
        if web is None:
            return f"*[missing: {target}]*"
        return img_tag(web, path.stem, ASSET_SIZES.get(web.lstrip("/")), option)

    def from_markdown(match: re.Match) -> str:
        alt, source = match.group(1), match.group(2).strip()
        if source.startswith("data:"):
            print(f"  warn     inline base64 image in {note.name} left as-is")
            return match.group(0)
        if source.startswith(("http://", "https://")):
            path = fetch_remote(source)
            if path is None:
                return match.group(0)
        else:
            path = find_in_vault(urllib_unquote(source), note)
            if path is None:
                print(f"  warn     missing image {source} in {note.name}")
                return f"*[missing: {source}]*"
        web = register_asset(path)
        if web is None:
            return match.group(0)
        return img_tag(web, alt, ASSET_SIZES.get(web.lstrip("/")))

    markdown = RE_EMBED.sub(from_embed, markdown)
    markdown = RE_MD_IMAGE.sub(from_markdown, markdown)

    # An italic line on its own directly under an image becomes its caption.
    markdown = RE_CAPTION.sub(
        lambda m: f"<figure>{m.group(1)}"
        f"<figcaption>{m.group(2).strip()}</figcaption></figure>\n",
        markdown,
    )

    # A block-level image needs blank lines around it, or pandoc treats the
    # following prose as part of the same raw HTML block and drops its <p>.
    markdown = re.sub(r"(?<!\n)\n(<(?:img|figure)[ >])", r"\n\n\1", markdown)
    markdown = re.sub(r"((?:</figure>|<img [^>]+>))\n(?!\n)", r"\1\n\n", markdown)
    # Gary sometimes types prose straight after an embed on the same line.
    # Split those, but leave an image used mid-sentence inline.
    markdown = re.sub(r"^(<img [^>]+>)(?=\S)", r"\1\n\n", markdown, flags=re.M)
    return markdown


def urllib_unquote(text: str) -> str:
    from urllib.parse import unquote

    return unquote(text)


# ─── PARSING ──────────────────────────────────────────────────────────────

RE_TITLE = re.compile(r"^#\s+(?P<title>.+?)\s*$")
RE_PUBLISHED = re.compile(r"^\*\*Published:\*\*\s*(?P<date>.+?)\s*$", re.I)
RE_SUBTITLE = re.compile(r"^\*\*Subtitle:\*\*\s*(?P<sub>.+?)\s*$", re.I)
RE_TAGLINE = re.compile(r"^#[\w/-]+(\s+#[\w/&-]+)*\s*$")
RE_RULE = re.compile(r"^-{3,}\s*$")
RE_DESCRIPTION = re.compile(r"^##\s+Description\s*$", re.M)
RE_NEXT_H2 = re.compile(r"^##\s+", re.M)


def parse_post(path: Path, slugs: dict) -> Post | None:
    """Parse one vault note. Returns None when the note has no Published line."""
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")

    title = ""
    date = None
    subtitle = ""
    index = 0

    # Consume the header run: title, then any order of Published / Subtitle /
    # tag line / horizontal rule / blank. Stop at the first line of real body.
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if not title and (match := RE_TITLE.match(line)):
            title = match.group("title")
            index += 1
            continue
        if match := RE_PUBLISHED.match(line):
            stamp = match.group("date").strip()
            for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y"):
                try:
                    date = datetime.strptime(stamp, fmt)
                    break
                except ValueError:
                    continue
            if date is None:
                print(f"  warn     unreadable date {stamp!r} in {path.name}")
            index += 1
            continue
        if match := RE_SUBTITLE.match(line):
            subtitle = match.group("sub")
            index += 1
            continue
        if RE_RULE.match(line) or RE_TAGLINE.match(line):
            index += 1
            continue
        break

    if not title:
        print(f"  skipped  {path.name} — no H1 title")
        return None
    if date is None:
        print(f"  skipped  {path.name} — no **Published:** line")
        return None

    body = "\n".join(lines[index:]).strip()

    # The "## Description" section becomes the lede, and its heading goes away.
    lede = ""
    if match := RE_DESCRIPTION.search(body):
        start = match.end()
        following = RE_NEXT_H2.search(body, start)
        end = following.start() if following else len(body)
        lede = body[start:end].strip()
        body = (body[: match.start()] + body[end:]).strip()

    stem = path.stem
    slug = slugs.get(stem) or slugify(stem)
    slugs[stem] = slug

    return Post(
        source=path,
        title=title,
        date=date,
        slug=slug,
        subtitle=subtitle,
        lede_md=lede,
        body_md=body,
    )


def render_post(post: Post) -> None:
    post.lede_html = tidy(pandoc(resolve_assets(post.lede_md, post.source)))
    post.body_html = tidy(pandoc(resolve_assets(post.body_md, post.source)))
    source = post.lede_md or post.body_md
    plain = " ".join(pandoc(source, to="plain").split())
    post.excerpt = plain[:197].rsplit(" ", 1)[0] + "…" if len(plain) > 200 else plain


# ─── TEMPLATES ────────────────────────────────────────────────────────────


def masthead() -> str:
    lines = "".join(f"<span>{line}</span>" for line in MASTHEAD[:-1])
    lines += f'<span>{MASTHEAD[-1]}<i class="cursor"></i></span>'
    return f'<a class="masthead" href="/">{lines}</a>'


def page(*, title: str, description: str, body: str, canonical: str,
         is_home: bool = False) -> str:
    full_title = title if is_home else f"{title} — {SITE['title']}"
    return f"""<!doctype html>
<html lang="{SITE['lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="author" content="{esc(SITE['author'])}">
<link rel="canonical" href="{SITE['url']}{canonical}">
<link rel="icon" href="{FAVICON}">
<link rel="alternate" type="application/rss+xml" title="{esc(SITE['title'])}" href="/feed.xml">
<link rel="preload" as="font" type="font/woff2" href="/fonts/roboto-mono-400.woff2" crossorigin>
<link rel="stylesheet" href="/style.css">
<meta property="og:type" content="{'website' if is_home else 'article'}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{SITE['url']}{canonical}">
<meta property="og:site_name" content="{esc(SITE['title'])}">
<meta name="twitter:card" content="summary">
</head>
<body>
<main class="shell">
{masthead()}
{body}
</main>
</body>
</html>
"""


def pagenav(older: Post | None, newer: Post | None) -> str:
    parts = []
    if older:
        parts.append(f'<a href="{older.url}" title="{esc(older.title)}">← Older</a>')
    else:
        parts.append("<span>← Older</span>")
    if newer:
        parts.append(f'<a href="{newer.url}" title="{esc(newer.title)}">Newer →</a>')
    else:
        parts.append("<span>Newer →</span>")
    parts.append('<a href="/about/">About</a>')
    parts.append('<a href="/">Index</a>')
    return f'<nav class="pagenav">{"".join(parts)}</nav>'


def footer() -> str:
    year = datetime.now().year
    return (
        f'<footer class="sitefooter">'
        f'<a href="/feed.xml">RSS</a> · '
        f'<a href="/about/">About</a> · '
        f"© {year} {esc(SITE['author'])}"
        f"</footer>"
    )


def render_index(posts: list[Post]) -> str:
    blocks = []
    current_year = None
    for post in posts:
        if post.date.year != current_year:
            current_year = post.date.year
            blocks.append(f'<div class="year">{current_year}</div>')
        sub = f'<span class="entry-sub">{esc(post.subtitle)}</span>' if post.subtitle else ""
        blocks.append(
            f'<div class="entry">'
            f'<span class="entry-date">{post.date_short}</span>'
            f'<a class="entry-title" href="{post.url}">{esc(post.title)}</a>'
            f"{sub}"
            f"</div>"
        )
    if not blocks:
        blocks.append('<p class="empty">Nothing published yet.</p>')
    body = "\n".join(blocks) + "\n" + footer()
    return page(
        title=SITE["title"],
        description=SITE["description"],
        body=body,
        canonical="/",
        is_home=True,
    )


def render_post_page(post: Post, older: Post | None, newer: Post | None) -> str:
    subtitle = f'<p class="subtitle">{esc(post.subtitle)}</p>' if post.subtitle else ""
    lede = f'<div class="lede">{post.lede_html}</div>' if post.lede_html else ""
    body = f"""<article>
<h1>{esc(post.title)}</h1>
{subtitle}
<div class="post-meta meta"><span class="key">×</span> Date: {post.date_long}</div>
{lede}
<div class="prose">
{post.body_html}
</div>
</article>
{pagenav(older, newer)}
{footer()}"""
    return page(
        title=post.title,
        description=post.excerpt,
        body=body,
        canonical=post.url,
    )


def render_about() -> str:
    if not ABOUT_SOURCE.exists():
        # This file is named directly, not discovered, so a move breaks it.
        die(
            f"about page missing: {ABOUT_SOURCE}\n"
            f"           Move it back, or fix ABOUT_SOURCE at the top of build.py."
        )
    raw = ABOUT_SOURCE.read_text(encoding="utf-8")
    lines = [
        line
        for line in raw.split("\n")
        if not RE_TITLE.match(line.strip()) and not RE_TAGLINE.match(line.strip())
    ]
    prose = tidy(pandoc(resolve_assets("\n".join(lines).strip(), ABOUT_SOURCE)))
    body = f"""<article>
<h1>About</h1>
<div class="prose">
{prose}
</div>
</article>
<nav class="pagenav"><a href="/">Index</a><a href="/feed.xml">RSS</a></nav>
{footer()}"""
    return page(
        title="About",
        description=SITE["description"],
        body=body,
        canonical="/about/",
    )


def render_404() -> str:
    body = f"""<div class="notfound">
<div class="big">404</div>
<p>There is nothing on this ground.</p>
</div>
<nav class="pagenav"><a href="/">Index</a><a href="/about/">About</a></nav>
{footer()}"""
    return page(
        title="Not found",
        description="Page not found.",
        body=body,
        canonical="/404.html",
    )


def render_feed(posts: list[Post]) -> str:
    # Stamp the feed with the newest post, not the clock. A build that changes
    # nothing then produces no diff, so ./publish stays quiet.
    now = posts[0].rfc822 if posts else "Thu, 01 Jan 1970 00:00:00 +0000"
    items = []
    for post in posts:
        content = post.lede_html + post.body_html
        items.append(
            f"""  <item>
    <title>{esc(post.title)}</title>
    <link>{SITE['url']}{post.url}</link>
    <guid isPermaLink="true">{SITE['url']}{post.url}</guid>
    <pubDate>{post.rfc822}</pubDate>
    <description>{esc(post.excerpt)}</description>
    <content:encoded><![CDATA[{content}]]></content:encoded>
  </item>"""
        )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{esc(SITE['title'])}</title>
  <link>{SITE['url']}/</link>
  <atom:link href="{SITE['url']}/feed.xml" rel="self" type="application/rss+xml"/>
  <description>{esc(SITE['description'])}</description>
  <language>{SITE['lang']}</language>
  <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items)}
</channel>
</rss>
"""


# ─── BUILD ────────────────────────────────────────────────────────────────


def collect(slugs: dict) -> list[Post]:
    posts: list[Post] = []
    for folder in SOURCES:
        if not folder.is_dir():
            # Most likely the folder was renamed in Obsidian. Say what is
            # actually there, so the fix is obvious.
            siblings = sorted(
                p.name for p in folder.parent.iterdir() if p.is_dir()
            ) if folder.parent.is_dir() else []
            hint = "\n           ".join(siblings) or "(nothing)"
            die(
                f"source folder missing: {folder}\n"
                f"           folders in {folder.parent}:\n"
                f"           {hint}\n"
                f"           Fix SOURCES at the top of build.py."
            )
        print(f"  reading  {folder}")
        for path in sorted(folder.glob("*.md")):
            if path.name in EXCLUDE or path == ABOUT_SOURCE:
                continue
            if post := parse_post(path, slugs):
                posts.append(post)
    posts.sort(key=lambda p: p.date, reverse=True)
    return posts


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def check_links() -> None:
    """Report internal links that point nowhere.

    Renaming a note changes its URL, which silently breaks every link the
    other posts make to it. This catches that before it ships.
    """
    def url_of(page: Path) -> str:
        rel = page.parent.relative_to(OUT).as_posix()
        return "/" if rel == "." else f"/{rel}/"

    pages = {url_of(p) for p in OUT.rglob("index.html")}
    static = {"/feed.xml", "/style.css", "/404.html", "/robots.txt"}
    broken = []
    for page in sorted(OUT.rglob("*.html")):
        markup = page.read_text(encoding="utf-8")
        for href in re.findall(r'href="(/[^"]*)"', markup):
            path, _, fragment = href.partition("#")
            if path in static:
                continue
            if path.startswith(("/images/", "/fonts/", "/files/")):
                if not (OUT / path.lstrip("/")).exists():
                    broken.append((page.parent.name, href, "missing file"))
                continue
            if path not in pages:
                broken.append((page.parent.name, href, "no such page"))
            elif fragment:
                target = (OUT / path.lstrip("/") / "index.html").read_text(encoding="utf-8")
                if fragment not in set(re.findall(r'id="([^"]+)"', target)):
                    broken.append((page.parent.name, href, "no such anchor"))

    if broken:
        print(f"  warn     {len(broken)} broken internal link(s):")
        for source, href, why in broken[:12]:
            print(f"           {source[:36]:<36} {href[:60]}  ({why})")


def main() -> None:
    check_only = "--check" in sys.argv

    if not PANDOC:
        die("pandoc not found. Install it with: brew install pandoc")

    slugs = load_slugs()
    posts = collect(slugs)
    if not posts:
        # An empty source folder is a valid state, not an error. The About
        # page and the feed still build, and the index says so plainly.
        print("  warn     no posts found — building an empty index")

    # Two titles that differ only past the trim point produce the same slug.
    # Give every member of a colliding group its untrimmed slug instead.
    grouped: dict[str, list[Post]] = {}
    for post in posts:
        grouped.setdefault(post.slug, []).append(post)
    for slug, group in grouped.items():
        if len(group) < 2:
            continue
        for post in group:
            post.slug = slugify(post.source.stem, limit=0)
            slugs[post.source.stem] = post.slug
        print(f"  note     {len(group)} posts collided on {slug!r}; using full slugs")

    seen: dict[str, str] = {}
    for post in posts:
        if post.slug in seen:
            die(f"slug collision: {post.slug!r} from {post.source.name} and {seen[post.slug]}")
        seen[post.slug] = post.source.name

    for post in posts:
        render_post(post)

    if check_only:
        for post in posts:
            flag = "sub" if post.subtitle else "   "
            print(f"  ok  {post.date.date()}  {flag}  /{post.slug}/")
        print(f"\n  {len(posts)} posts parsed, nothing written")
        return

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    write(OUT / "index.html", render_index(posts))
    for i, post in enumerate(posts):
        newer = posts[i - 1] if i > 0 else None
        older = posts[i + 1] if i + 1 < len(posts) else None
        write(OUT / post.slug / "index.html", render_post_page(post, older, newer))
    write(OUT / "about" / "index.html", render_about())
    write(OUT / "404.html", render_404())
    write(OUT / "feed.xml", render_feed(posts))
    write(OUT / ".nojekyll", "")
    write(OUT / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE['url']}/feed.xml\n")
    shutil.copy2(ROOT / "style.css", OUT / "style.css")
    if (ROOT / "fonts").is_dir():
        shutil.copytree(ROOT / "fonts", OUT / "fonts")

    for name, data in ASSETS.items():
        target = OUT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if ASSETS:
        weight = sum(len(d) for d in ASSETS.values()) / 1024
        print(f"  assets   {len(ASSETS)} files, {weight:.0f} KB")

    save_slugs(slugs)

    check_links()

    files = sum(1 for _ in OUT.rglob("*") if _.is_file())
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"  {len(posts)} posts → {len(posts) + 3} pages")
    print(f"  wrote    docs/ ({files} files, {size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
