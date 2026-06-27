# PDF Page Export — Design

**Date:** 2026-06-24
**Status:** Approved

## Summary

Add a third PDF mode, **PDF → Pages**, to the Media Converter web UI. From a source
PDF, the user selects one or more pages — by clicking page thumbnails, by typing a page
range (`1,3,5-7`), or both (the two views stay in sync) — and exports them either as a
single combined PDF or as one PDF per page.

Extraction is **lossless**: selected pages are copied with their real text and vector
content preserved (PyMuPDF `insert_pdf`), not rasterized to images.

## Goals

- Export a single page or multiple pages of a PDF into a new PDF file.
- Two selection methods that stay in sync: visual thumbnail picker **and** a text page-range box.
- User chooses output grouping per export: one combined PDF, or one PDF per page.

## Non-Goals (YAGNI)

- Reordering pages (selection always exports in ascending page order).
- Rotating, deleting in place, or otherwise editing the source PDF.
- Client-side PDF rendering / PDF.js (keeps `index.html` self-contained).
- Server-side caching of the uploaded PDF (server stays stateless).

## Architecture

The feature reuses the existing patterns exactly: PDF logic lives in
`pdf_convert/pdf_converter.py` (testable + shared with the CLI), and the Flask server in
`server.py` exposes thin, **stateless** HTTP routes. The browser holds the `File` object
and sends its bytes on each request.

### New logic in `pdf_convert/pdf_converter.py`

1. **`parse_page_ranges(text, page_count) -> list[int]`**
   - Parses `"1,3,5-7"` into a validated, de-duplicated, ascending list of 1-based page numbers.
   - Accepts single numbers, comma-separated lists, and `a-b` ranges (inclusive).
   - Rejects out-of-range or unparseable input by raising `ValueError`.
   - This is the single source of truth for selection; the JS mirrors its parsing so the
     text box and thumbnail highlights agree.

2. **`pdf_thumbnails(pdf_bytes, dpi=40) -> list[tuple[int, bytes]]`**
   - Renders every page to a small PNG at low DPI for the picker.
   - Returns `[(page_number, png_bytes), …]`, 1-based.

3. **`extract_pdf_pages(pdf_bytes, pages, combine=True) -> list[tuple[str, bytes]]`**
   - Copies the given pages (1-based, ascending) losslessly via PyMuPDF `insert_pdf`.
   - `combine=True`  → `[("extracted.pdf", bytes)]` (one PDF, pages in order).
   - `combine=False` → `[("page_001.pdf", bytes), …]` (one PDF per page).

### New routes in `server.py`

- **`POST /api/pdf/thumbnails`** — accepts the PDF file; returns
  `{ "page_count": N, "thumbnails": [ { "page": 1, "dataUrl": "data:image/png;base64,…" }, … ] }`.
- **`POST /api/pdf/extract`** — accepts the PDF file + `pages` (e.g. `"1,3,5-7"`) +
  `combine` (`true`/`false`). Returns:
  - `combine=true` → a single `<stem>_extracted.pdf`.
  - `combine=false`, 1 page → `<stem>_page_N.pdf`.
  - `combine=false`, >1 page → `<stem>_pages.zip` (reusing the existing zip pattern from
    `/api/pdf/to-images`).
  - Sets `X-Before-Size` / `X-After-Size` headers like the other routes.

Errors (corrupt PDF, out-of-range/empty page selection) return `{ "error": … }` with a
4xx/5xx status, surfaced in the UI the same way existing route errors are.

## UI (`index.html`)

The PDF tab's mode toggle gains a third button:
**Images → PDF · PDF → Images · PDF → Pages**.

When **PDF → Pages** is active:

```
┌─────────────────────────────────────────────┐
│  Drop a PDF here or click to browse           │
└─────────────────────────────────────────────┘

Pages:  [ 1,3,5-7              ]   ← syncs with thumbnails
Output: ( • One combined PDF ) ( ○ One PDF per page )

┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐
│ ✓1 │ │  2 │ │ ✓3 │ │  4 │ │ ✓5 │   ← click to toggle
└────┘ └────┘ └────┘ └────┘ └────┘

                              [ Export ]
```

- Dropping a PDF calls `/api/pdf/thumbnails`; thumbnails render and **all pages start selected**.
- Clicking a thumbnail toggles its selection and rewrites the **Pages** box.
- Typing in the **Pages** box re-parses and updates the highlighted thumbnails.
- The **Output** toggle (combined / per-page) reuses the existing `.fmt-btn` option-picker styling.
- **Export** is disabled when zero pages are selected.

## Data Flow

```
Drop PDF
  → POST /api/pdf/thumbnails  (file bytes)
  ← { page_count, thumbnails: [ {page, dataUrl}, … ] }
  → render thumbnails, select all

Click Export
  → POST /api/pdf/extract  (file bytes + pages + combine)
  ← combine=true            → <stem>_extracted.pdf
  ← combine=false, 1 page   → <stem>_page_N.pdf
  ← combine=false, >1 page  → <stem>_pages.zip
```

## Error Handling

- Empty selection → Export disabled client-side; server also rejects empty/invalid `pages` with 400.
- Out-of-range page numbers → `parse_page_ranges` raises `ValueError` → 400 `{error}`.
- Corrupt / non-PDF upload → PyMuPDF raises → 500 `{error}`.

## Testing (`test_pdf.py`)

- **`parse_page_ranges`** — single page, comma list, `a-b` range, mixed, whitespace
  tolerance, de-dupe + ascending order, out-of-range rejection, empty/garbage rejection.
- **`extract_pdf_pages`** — combined output page count matches selection; per-page output
  count matches; output is valid PDF with text/vector content preserved (not rasterized).
- **`pdf_thumbnails`** — returns exactly one image per page, 1-based numbering.

## CLI (parity, optional within scope)

Extend `pdf_convert/pdf_converter.py`'s `main()` with a third direction
(`3 = extract pages`): prompt for PDF path, page range, and combine yes/no; write output
next to the source. Keeps the CLI in step with the web UI, consistent with the existing
two directions.
