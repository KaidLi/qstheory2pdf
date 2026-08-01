# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

qstheory2pdf converts articles from 求是网 (qstheory.cn) into PDF or EPUB files. The tool supports two content modes:
- **Single article mode**: Download one article → one PDF
- **Issue mode**: Download all articles from a magazine issue's table of contents → single combined PDF

## Architecture

```
src/
  qstheory2pdf/
    __init__.py        # Re-exports QiuShiCrawler, PDFGenerator; declares __version__
    types.py           # Domain contracts: source documents, Article, Issue, IssueEntry, semantic body unions
    crawler.py         # Data layer: classify/fetch/parse HTML from qstheory.cn
    domain.py          # Completeness invariants and reconstruction diagnostics
    gen_pdf.py         # Presentation layer: build .tex, compile via xelatex
    gen_epub.py        # Presentation layer: build reflowable EPUB via EbookLib
    entry.py           # CLI entry point (argparse)
    resource/
      template.tex     # LaTeX template for single article
      qiushi.cls       # LaTeX document class (forked ElegantNote, options trimmed)
scripts/
  discover_issue.py    # Auto-discover latest issue URL from qstheory.cn (for CI)
.github/workflows/
  build-issue.yml      # GHA: cron + workflow_dispatch → build → Release
```

### Data flow

The data layer (`crawler.py`) and presentation layer (`gen_pdf.py`) communicate through TypedDicts defined in `types.py`. This is the single source of truth for the schema; mypy/Pyright will catch drift.

1. **entry.py** receives a URL and requests one semantic source document.
2. **crawler.py** (`QiuShiCrawler`):
   - `fetch_document(url) → SourceDocument` — one request, classifies `article | issue_contents | issue_catalog` from source semantics.
   - `fetch_info(url, *, with_qr) → Article` — compatibility method for a source that must classify as an article.
   - Body extraction preserves semantic roles, inline emphasis/editorial links, lists, tables, quotes and multi-image figures; unsupported substantive structures make reconstruction partial.
3. **domain.py** validates article/issue completeness before rendering.
4. **gen_pdf.py** (`PDFGenerator`) / **gen_epub.py** (`EPUBGenerator`):
   - `start()` — creates a tempdir, returns the image subdir path.
   - `gen_single(article) / gen_issue(issue, articles, ...)` consume the domain model.
   - `finish()` — removes the tempdir (and all downloaded images).
   - EPUB reuses the same `Article` and image directory, and does not require xelatex.

`CONTEXT.md` is authoritative for domain terms and completeness rules. Complete reconstruction is the default; `--allow-partial` is the explicit, visibly marked exception.

**Image lifecycle is explicit**: `crawler.image_dir` is set by the caller (typically `pdf_gen.start()`'s return value); the crawler writes article figures and the optional QR code into it. No shared CWD-relative state.

### Device presets (in qiushi.cls)

| Device | Paper size |
|--------|-----------|
| `normal` | A4 (默认) |
| `pad` | 6×8 in |
| `kindle` | 3.68×4.92 in (old Kindle) |
| `scribe` | 5.83×7.76 in (Kindle Scribe) |
| `screen` | 25.4×19.05 cm |
| `pc` | 6.2×6 in |

## 求是网站 Structure (2026)

Code targets the current (2026) website. Key extraction points:

- Title: `//h1/text()`
- Metadata: `<span class="appellation">` elements for volume (`来源：《求是》2026/08`) and author (`作者：XXX`)
- Article links in TOC: `//div[contains(@class,'content')]//p[.//a]` (must use `p[.//a]`, not `p[a]` — some links are nested inside `<span>`)
- Content paragraphs: `//div[contains(@class,"content")]//p`, skip preamble via body_start detection
- Images: `<img>` inside `<p>`, QR images contain `zxcode` in src
- URL pattern: `https://www.qstheory.cn/YYYYMMDD/{32-char-hash}/c.html` — the 32-character hash is the source article identifier. URL path dates are not publication dates; dates are accepted only from explicit official page fields.

Detailed XPath reference in memory: `reference_new_website_structure.md`.

### chinesefont modes (cross-platform)

| Mode | fontset | Works on |
|------|---------|----------|
| `ctexfont` (default) | `windows` | Windows |
| `founder` | `none` + Founder fonts | Needs FZ fonts (not currently selected by the cls) |
| `nofont` | `none` | Any (manual setup) |

For GitHub Actions (Ubuntu runner), the default `ctexfont`/`windows` won't work. Only one change needed: `fontset=windows` → `fontset=fandol` in `qiushi.cls`. The CI workflow does this with a `sed` command. README: 3-line section.

### Sample URLs
- TOC page (2026年第8期): `https://www.qstheory.cn/20260415/94280df5956349b0954c44d728bb75a1/c.html`
- Sample article: `https://www.qstheory.cn/20260415/eb2be76d239d4fa4a0ef3a9a9d82b970/c.html`

## Commands

```bash
# Setup environment (uv)
uv sync

# Run the tool (via uv)
uv run qstheory2pdf <url>
uv run qstheory2pdf --format epub <url>
uv run qstheory2pdf --format both <url>
uv run qstheory2pdf --allow-partial --format both <url>  # diagnostics/previews only
uv run qstheory2pdf <url> -d scribe
uv run qstheory2pdf <url> -d scribe -o output/custom.pdf

# Run directly (without uv)
uv run python -m qstheory2pdf.entry <url>

# Required system dependency
# xelatex (from texlive) must be available (gen_pdf._find_xelatex() locates it)
```

PDF files are saved to the `output/` directory by default (created automatically).

## Dependencies

- **Python (>=3.10)**: requests, lxml, qrcode, pillow>=10.4.0 (managed by uv)
- **System**: xelatex (texlive) for PDF compilation

### Resolved (2026-06-03)
- `gen_pdf.py:34` used `qiushi2pdf.__file__` instead of `qstheory2pdf.__file__` — NameError after project rename.
- Windows Git Bash garbled Chinese output — `sys.stdout.encoding` defaults to GBK. Fixed in `entry.py`: `sys.stdout.reconfigure(encoding="utf-8")`.
- Single-article mode xelatex crash — `img\qrcode.png` backslash parsed as LaTeX control sequence. Fixed in `gen_pdf.py`: `.replace("\\", "/")`.
- README rewritten for newcomers: `uv run` commands, cross-platform font guidance, troubleshooting table, acknowledgment to original project.
- Cross-platform font guidance propagated to README.md.
- Temp file cleanup: `_cleanup()` now does full `shutil.rmtree` on the xelatex tempdir.
- GitHub Actions auto-release: cron (1st, 16th) + workflow_dispatch. Auto-discovers latest issue via `qs/mulu.htm` → year index, deduplicates by `gh release view <tag>`, builds PDF, publishes Release with `qstheory-YYYY-NN` tag. Font fix: single `sed` to switch fontset.
- `scripts/discover_issue.py`: auto-discovery script, outputs JSON `{url, volume, tag}`. Supports manual URL override for workflow_dispatch.
- README font section simplified to 3-line one-command instruction (fontset switch only).
- **Structural refactor (2026-06-03)**:
  - TypedDict contracts in `types.py` (Article, TextBlock, ImageBlock, TocEntry, TocResult) make the data flow between crawler and gen_pdf statically checkable.
  - `crawler.py` no longer knows about LaTeX — `add_backslash4space`, `_strip_tags`, `_inner_html_to_latex` deleted; all LaTeX formatting is centralized in `gen_pdf.py:format_text_to_latex()`.
  - Image lifecycle made explicit: `QiuShiCrawler(image_dir=...)`; `PDFGenerator.start()` creates and returns the image dir; `PDFGenerator.finish()` cleans it up. No more CWD-relative `img/` shared across modules.
  - `fetch_toc()` merges the old `fetch_urls()` + `fetch_toc_entries()` into one HTTP request.
  - Dead code removed: `pypdf` dependency, `src/test.py` stub, `color` content-block key, `src/qiushi2pdf.egg-info/` legacy artifact.
  - `qiushi.cls` option surface trimmed: removed unused color variants (green/cyan/sakura/brown), `en` lang, `geye/hazy/sepia` mode, `founder/nofont` chinesefont, `citestyle/bibstyle/bibend/biber/bibtex`, `10pt/12pt` fontsize, `newtx/mtpro2` math. Storage declarations kept (still consumed by cls body).
  - `discover_issue.py` reuses `QiuShiCrawler.session` (with User-Agent), wraps network errors with `exit 2`.
  - CI: `timeout-minutes: 30`; smoke-test step (`import qstheory2pdf`); `if: failure()` step uploads build logs.
  - `gen_pdf._compile()` now uses `subprocess.run(..., timeout=300)` to avoid hanging runners.
  - `__version__` synced to 0.1.0; `requires-python` raised to >=3.10 (code uses PEP 604 union syntax).

### Robustness updates (2026-07-27)
- Article metadata now falls back from `span.appellation`/`h1` to Open Graph, standard meta fields, and JSON-LD.
- Downloaded image names include a URL hash, preventing same-name collisions and query-string filenames.
- Complete reconstruction is required by default; `--allow-partial` is explicit and marked. `--strict` remains one minor version as a deprecated alias for the default.
- The release workflow checks the CLI's machine-readable reconstruction status before publishing.
- Release EPUB files must pass W3C EPUBCheck before publication.
- Local regression coverage includes crawler, discovery, PDF rendering, EPUB packaging, CLI completeness policy, and workflow gates.
