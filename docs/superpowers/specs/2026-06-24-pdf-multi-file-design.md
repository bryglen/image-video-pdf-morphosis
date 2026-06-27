# PDF Multi-File (Batch) — Design

**Date:** 2026-06-24
**Status:** Approved

## Summary

Let the PDF tab accept multiple PDFs at once across all its modes. **Compress** and
**PDF → Images** become batch: drop N PDFs, each is processed independently and gets its own
download in the queue. **PDF → Pages** gains per-PDF sections: each dropped PDF shows its own
thumbnail strip and page-range box with independent selection, and Export bundles every PDF's
output into a single `pages.zip`.

The Image and Video tabs already accept multiple files, so no change is needed there.

## Goals

- Drop/select multiple PDFs in Compress, PDF → Images, and PDF → Pages.
- Compress / PDF → Images: per-file processing, per-file download (no combined zip).
- PDF → Pages: independent page selection per PDF; one combined `pages.zip` on Export
  (or a single file when only one output is produced).

## Non-Goals (YAGNI)

- Batch in the CLI (the request is about the web UI drop zone; CLI keeps its single-file flow).
- Cross-PDF page operations (merging selected pages from different PDFs into one document).
- Client-side zipping (no external JS libraries; zipping happens server-side).

## Changes by Mode

### Compress (batch) — frontend only
- Enable `multiple` on the file input in compress mode; stop capping to one file.
- Each dropped PDF renders as a queue row (existing `pdfRenderItem`). The existing compress
  click-loop already iterates `pdfFiles` and calls `pdfCompressOne` per item, each producing its
  own `before → after · engine` line and Download link. No server change.

### PDF → Images (batch) — frontend only
- Enable `multiple`; stop capping to one file.
- The existing convert loop calls `pdfConvertOne` per item; each PDF yields its own image/ZIP
  and Download link. No server change.

### PDF → Pages (batch, per-PDF sections) — frontend + server

**Server — new pure function (`pdf_convert/pdf_converter.py`):**

```python
extract_pdf_pages_batch(items, combine=True) -> list[tuple[str, bytes]]
```
- `items`: `list[(filename, pdf_bytes, pages)]` where `pages` is a 1-based list.
- For each item, calls the existing `extract_pdf_pages(pdf_bytes, pages, combine)`:
  - `combine=True`  → one output named `<stem>_extracted.pdf`.
  - `combine=False` → outputs named `<stem>_page_001.pdf`, `<stem>_page_003.pdf`, …
- Returns a **flat** list of `(name, bytes)` with names made **unique** across the whole batch
  (on collision, suffix ` _2`, `_3`, … before the extension), so two same-named source PDFs
  don't clobber each other in the zip.

**Server — new route:** `POST /api/pdf/extract-batch`
- Accepts parallel lists: `request.files.getlist("file")` and `request.form.getlist("pages")`
  (same order), plus `combine` (`true`/`false`).
- For each file: `parse_page_ranges(pages[i], pdf_page_count(bytes))`; a `ValueError` → 400 with
  an error message naming the offending file.
- Builds `items`, calls `extract_pdf_pages_batch`. Then, mirroring the existing single routes:
  - exactly **one** output → return it directly (e.g. `<stem>_extracted.pdf`).
  - **multiple** outputs → one `pages.zip` containing them.
- Headers `X-Before-Size` (sum of inputs) / `X-After-Size` (payload), exposed via
  `Access-Control-Expose-Headers`.
- The existing single-PDF `POST /api/pdf/extract` route remains available; the UI now uses
  `extract-batch` for PDF → Pages.

**Frontend — per-PDF section model (`index.html`):**
- Replace the single-PDF page-picker state (`pdfPagesFile`, `pdfSelected`, `pdfPageCount`) with
  a list `pdfSections`, each entry: `{ id, file, pageCount, selected: Set<int>, inputEl }` plus
  its DOM nodes.
- On drop in pages mode (one or many PDFs): for each PDF, append a **section** to `pdfThumbs`
  containing a header (filename + a per-section page-range input) and a thumbnail strip; fetch
  `/api/pdf/thumbnails` for that file; render thumbnails with all pages selected by default.
- Per-section sync (independent): clicking a thumbnail toggles that section's `selected` and
  rewrites that section's page-range input; typing in a section's input re-parses
  (`parsePageRanges`) and re-highlights that section's thumbnails. Reuses the existing
  `parsePageRanges` / `pagesToText` helpers, scoped per section.
- The combined/per-page **Output** toggle (`pdfCombine`) applies to all sections.
- **Export**: build one `FormData` appending `file` + `pages` for each section that has a
  non-empty selection, plus `combine`; POST to `/api/pdf/extract-batch`; download the returned
  file (`pages.zip`, or a single file when only one output). Export is disabled when no section
  has a selection.

## Data Flow (PDF → Pages batch)

```
Drop N PDFs → N sections; per PDF: POST /api/pdf/thumbnails → render strip, select all
Click Export
  → POST /api/pdf/extract-batch  (file[i], pages[i] for each selected section, combine)
  ← one output  → <stem>_extracted.pdf
  ← many outputs → pages.zip   (entries: <stem>_extracted.pdf or <stem>_page_NNN.pdf, unique)
```

## Error Handling

- A section with an empty selection is skipped (not sent).
- Invalid page range for a file → batch route returns 400 `{error}` naming the file; the UI
  alerts the message.
- Corrupt/non-PDF in a section → thumbnails call shows an error in that section; other sections
  are unaffected.

## Testing (`test_pdf.py`)

- `extract_pdf_pages_batch` combined: two PDFs → two outputs `<stem>_extracted.pdf`, each a valid
  PDF with the right page count.
- `extract_pdf_pages_batch` per-page: outputs named `<stem>_page_NNN.pdf`, one PDF page each.
- `extract_pdf_pages_batch` single item combined → exactly one output.
- `extract_pdf_pages_batch` duplicate-stem inputs → names are unique (collision suffixing).
- Batch route exercised via curl (single output → pdf; multiple → zip with expected names;
  bad range → 400).

## README

Note in the PDF Converter section that all PDF modes accept multiple PDFs: Compress and
PDF → Images process each file independently (per-file download); PDF → Pages shows a section
per PDF and exports a combined `pages.zip`.
