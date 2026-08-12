# Investing on Rough Ground

A text-first site, generated from an Obsidian vault and served by GitHub Pages.

Live at **https://garyheffernan.github.io**

---

## Publishing a post

1. Write the note in Obsidian, inside `Writing/ROUGH GROUND/`.
2. Start it with an H1 title.
3. Add a `**Published:**` line.
4. Run `./publish`.

That is the whole contract. No frontmatter, no slugs, no config.

```markdown
# Upside in a "Dying" Industry? The Asymmetric Value of CEIX

**Published:** June 15, 2023

**Subtitle:** Why the market misreads a shrinking industry

## Description

One or two sentences. This becomes the lede, the search-result summary,
and the RSS excerpt.

## First Section

Body text.
```

Three lines are optional:

- `**Subtitle:**` renders as the grey subtitle under the title.
- `## Description` becomes the lede, and the word "Description" disappears.
- A `---` rule before a heading gets removed, because headings carry their own rule.

A note with no `**Published:**` line gets skipped, and the build says so. That is the safety catch against publishing a draft.

## The About page

The About page is a page, not a post. It reads one named file:

```python
ABOUT_SOURCE = VAULT / "ROUGH GROUND" / "About.md"
```

It sits inside the posts folder, and the collector skips it by path. So it needs no `**Published:**` line and never appears in the index or the feed. Its H1 and its `#draft` tag get stripped; everything else renders as written.

Moving that file stops the build with a message naming the path it expected.

## Commands

| Command | What it does |
|---|---|
| `./preview` | Builds, then serves on http://localhost:8080 |
| `./publish` | Builds, commits, pushes. Live in about a minute |
| `python3 build.py --check` | Parses and reports, writes nothing |
| `python3 fetch_fonts.py` | Re-downloads the webfonts. Needed once only |

## URLs

The URL comes from the **filename**, not the title. `A Note on Coal.md` becomes `/a-note-on-coal/`.

Rename files whenever you like. The URL follows the new name, and the old address stops working — which is fine, because nothing else depends on it.

Two titles that differ only past the 60-character cut would collide. The build detects that and gives both their untrimmed slug instead.

## Linking between your own posts

**Always use a wikilink. Never type a URL.**

```markdown
[[Liquidia Gold]]                        the note's own name as the text
[[Liquidia Gold|Part 1 here]]            your own words as the text
[[Connections You Can Count On#AI Summary|jump to the summary]]   a heading
```

The build turns each one into the target's current URL. Obsidian rewrites the note name inside the wikilink whenever you rename a file, so the link survives by construction. A typed URL does not.

An unknown note does not break the build. It warns and renders as plain text:

```
warn     wikilink to unknown note [[Liqiudia Gold]] in Prior art.md
```

Every build also validates every internal link and anchor, and reports anything pointing nowhere.

## Publishing more folders

`build.py` reads one folder today:

```python
SOURCES = [VAULT / "ROUGH GROUND"]
```

Add a line to widen it:

```python
SOURCES = [VAULT / "ROUGH GROUND", VAULT / "THOUGHTS IN PROGRESS" / "Completed"]
```

If you rename the folder in Obsidian again, the next build stops and lists the folders it can see. Change `SOURCES` to match and it works again. Renaming a *folder* is safe. Renaming a *file* changes that post's URL.

Those five finished pieces carry images, which need handling first. See "Images" below.

## Images

Paste an image into Obsidian as you normally would. The build finds it, copies it, and sizes it. Nothing else is required.

| You write | What happens |
|---|---|
| `![[Pasted image 20260131101501.png]]` | Found anywhere in the vault by filename |
| `![alt text](some image.png)` | Same, and the alt text is kept |
| `![alt](https://example.com/x.png)` | Downloaded once and self-hosted |
| `![[report.pdf]]` | Becomes a download link, not an image |
| `![[photo.heic]]` | Converted to JPEG, because HEIC does not render on the web |

Every file lands in `docs/images/` under a content-hashed name, such as `pasted-image-20260131101501-60800f41.png`. The hash means browsers cache it forever, and editing the image produces a new filename rather than a stale copy.

Each `<img>` gets `loading="lazy"` and its true pixel dimensions, so the page does not jump around while images load.

### Captions

Put an italic line on its own directly under an image:

```markdown
![[Pasted image 20260104160206.png]]

*Northern Appalachia cost curve, 2025.*
```

That renders as a `<figure>` with a centred grey caption. Without it, you just get the image.

### When something is missing

A broken embed does not stop the build. It leaves a visible marker in the text and warns:

```
  warn     missing embed [[This File Does Not Exist.png]] in OCC2.md
```

### Weight

The build converts PNG and JPEG to WebP at quality 82, cached by content hash in `.cache/webp/`. That cut the site from 16.0MB to 5.2MB, and the heaviest post from 5.5MB to 1.1MB.

**Your vault keeps the originals.** Conversion happens on the way into `docs/` only, so Obsidian is unaffected and the whole thing is reversible. If WebP comes out larger than the original — which happens on small flat PNGs — the original is kept.

GIFs are left alone. Converting them needs `gif2webp` and saved only 15% on the one animated GIF, which is not worth risking the animation.

Requires `cwebp`. Without it the build still works and just serves the originals.

Images imported from Substack were also downscaled to 1300px, which is 2× the column width. See `import_substack.py`.

## Design

Hand-written CSS, no framework, no JavaScript. Five decisions carry the look:

1. Monospace body at 15px with 28px line-height.
2. A 650px shell with 25px gutters, giving a 600px measure of about 66 characters.
3. Highlighter marks on links instead of underlines. Yellow leaves the site, grey stays.
4. Images bleed past the text column.
5. A near-invisible `#CAD2D4` for subtitles, section numbers and quiet links.

Headings use the system sans, which is SF Pro on Apple hardware. Body uses self-hosted Roboto Mono, three weights, 78KB total.

Dark mode follows the system setting.

A post page weighs about 5KB of HTML. The reference site, julian.digital, ships 1.7MB.

## Layout

```
build.py         the generator
fetch_fonts.py   one-time font download
preview          local server
publish          build + commit + push
style.css        the stylesheet
slugs.json       frozen permalinks
fonts/           three woff2 files
docs/            build output, served by Pages
```

`docs/` is generated. Never edit it by hand, because every build wipes it.

## Hosting

GitHub Pages serves the repo `garyHeffernan.github.io` from `main`, folder `/docs`.

If `./publish` fails with a 401, the credential has expired:

```
gh auth refresh -h github.com -s repo && gh auth setup-git
```

## Subscribing

Readers get three routes, gathered in the box at the foot of every page and on
`/subscribe/`: the RSS feed, X, and email.

The RSS link points at `/subscribe/`, not at `feed.xml`. A browser shows a feed
as raw XML, which reads as broken. Browsers used to fix that with an XSLT
stylesheet, but Chrome removes XSLT on 17 November 2026, so a plain page is the
durable answer. Feed readers still find `feed.xml` from the `<head>` tag.

### Switching email on

Set one value in `build.py`:

```python
BUTTONDOWN_USER = "your-buttondown-username"
```

The email field then appears in the box and on `/subscribe/`. While the value is
`None` the box renders without the field, so the site never shows a dead form.

The form is plain HTML posting straight to Buttondown. It needs no JavaScript,
and the page loads nothing from Buttondown until someone submits it.

### Emailing each new post

`send_email.py` does by hand what Buttondown's RSS automation add-on charges
$9/month for. It compares `docs/feed.xml` against `sent.json` and creates one
Buttondown email per unsent post. The API is free on every plan.

```
python3 send_email.py --dry-run   # report what would send
python3 send_email.py --seed      # mark everything current as already sent
python3 send_email.py             # create the emails
```

`sent.json` is the ledger, and it is committed. State stays visible and
diffable, and nothing is inferred from timestamps, so a rebuild cannot re-send
an old post.

Emails are created as **drafts** by default. Gary reads the draft in Buttondown
and presses send. Set `SEND_IMMEDIATELY = True` in `send_email.py` to skip that.

`.github/workflows/email-new-posts.yml` runs the script whenever a push changes
`docs/feed.xml`. It needs one repository secret, `BUTTONDOWN_API_KEY`, added
under Settings → Secrets and variables → Actions.

## Requirements

- Python 3, standard library only
- pandoc, for the markdown conversion

## Glossary

- **Frontmatter** — a YAML block at the top of a markdown file, holding title and date. This site needs none.
- **Ledger** — here, `sent.json`, the record of which posts have been emailed.
- **Lede** — the opening summary paragraph of an article.
- **Measure** — the width of a text column, counted in characters.
- **Slug** — the URL-safe form of a title, used as the address of a page.
- **XSLT** — a language for turning XML into HTML, which browsers drop in 2026.
