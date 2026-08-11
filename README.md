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

`slugs.json` freezes that mapping on first publish. Editing a title never breaks a live link. Renaming the file does, so rename before publishing, not after.

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

Images dominate page weight. A post with 15 pasted screenshots runs about 3.5MB, against 5KB for the HTML. Obsidian pastes at full retina resolution, often 2000px wide or more, when the column only shows 650px.

Downscaling anything wider than 1300px would cut that roughly in half with no visible loss. Not implemented — ask if you want it.

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

## Requirements

- Python 3, standard library only
- pandoc, for the markdown conversion

## Glossary

- **Frontmatter** — a YAML block at the top of a markdown file, holding title and date. This site needs none.
- **Lede** — the opening summary paragraph of an article.
- **Measure** — the width of a text column, counted in characters.
- **Slug** — the URL-safe form of a title, used as the address of a page.
