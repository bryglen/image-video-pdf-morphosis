# Image ⇄ PDF Converter Tab — Design

**Date:** 2026-06-23
**Component:** Media Converter (new web tab + CLI + shared module)

## Goal

Add a third tab, **📄 PDF**, that converts images → PDF and PDF → images, in the
web UI and as a CLI tool — following the same shared-module pattern as the image
and video converters.

## UX — the PDF tab

A mode toggle at the top (existing `.fmt-btn` button-group style) switches direction:

- **Images → PDF** (default mode)
  - Accepts image files (same input types as the Image tab, incl. HEIC).
  - A **Combine** toggle: ON (default) = all queued images become pages of one
    multi-page PDF, in queue order, one download; OFF = one PDF per image
    (per-file flow like the Image tab).
  - Output: combined `combined.pdf`, or `<stem>_converted.pdf` per image.
- **PDF → Images**
  - Accepts a single `.pdf`.
  - Options: **format** (PNG default / JPG), **DPI** (72 / 150 default / 300).
  - Each page renders to an image. Output: a **ZIP** (`page_001.png` …) for
    multi-page PDFs; the image directly if the PDF has one page.

The drop zone's `accept` switches with the mode (images vs `application/pdf`).
The Combine toggle shows only in Images→PDF; format/DPI rows show only in
PDF→Images.

## Backend

### New shared module `pdf_convert/pdf_converter.py` (logic + CLI)

Mirrors `image_convert/image_converter.py`: a `sys.path` bootstrap to the repo
root (consistency; no shared import needed yet), `register_heif_opener()` so
HEIC images convert to PDF, plus:

- `images_to_pdf(images) -> bytes` — `images` is a list of PIL Images. Each is
  flattened to RGB on white (PDF has no alpha). Returns one multi-page PDF via
  `images[0].save(buf, "PDF", save_all=True, append_images=images[1:])`. Raises
  `ValueError` on empty input.
- `pdf_to_images(pdf_bytes, fmt="png", dpi=150) -> list[(filename, bytes)]` —
  opens with PyMuPDF (`fitz.open(stream=pdf_bytes, filetype="pdf")`), renders
  each page at `zoom = dpi/72` via `page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))`,
  and `pix.tobytes("jpg"|"png")`. Filenames `page_001.<ext>`, 1-based, zero-padded.
- `PDF_IMAGE_FORMATS = {"png", "jpg", "jpeg"}`; CLI choice lists.
- `main()` CLI: prompts for direction; Images→PDF (path to file/folder, combine
  y/n, output path); PDF→Images (path to pdf, format, dpi, output dir).

### `server.py` routes

- `POST /api/pdf/from-images` — accepts one or more `file` parts; opens each with
  PIL; `images_to_pdf(...)` → returns the PDF (`mimetype application/pdf`,
  `download_name` = `combined.pdf` if >1 input else `<stem>_converted.pdf`). The
  server always combines the images it receives into one PDF; the **Combine
  toggle is a client concern** (combine ON → one request with all files; OFF → one
  request per file). Sends `X-Before-Size`/`X-After-Size` headers like the image
  route.
- `POST /api/pdf/to-images` — one `file` (PDF) + `format` + `dpi`;
  `pdf_to_images(...)`; if one page → send the image directly; if many → build an
  in-memory ZIP (`zipfile`) → send as `<stem>_pages.zip`.

Imports: `from pdf_convert.pdf_converter import images_to_pdf, pdf_to_images`.

## Dependency

Add **`pymupdf`** to `pyproject.toml` dependencies and `pip install pymupdf`
into the running environment. Image→PDF needs only Pillow (already present).

## Data flow

```
Images→PDF: UI (combine?) → /api/pdf/from-images (1..N files) → images_to_pdf → PDF
PDF→Images: UI (fmt,dpi)  → /api/pdf/to-images (1 pdf)        → pdf_to_images → ZIP | image
```

## Error handling

- Empty/again no file → 400 with JSON error (match existing routes).
- `images_to_pdf` on a non-image upload → caught, 500 JSON error.
- Corrupt/encrypted PDF → `fitz.open` raises; caught, 500 JSON error.
- Unknown `format` → default to PNG.

## Testing

`test_pdf.py` (repo root, plain-`assert` + `__main__` runner; needs pillow + pymupdf):
- Round-trip: two PIL images (e.g. 200×100 and 100×200) → `images_to_pdf` →
  assert bytes start with `%PDF` and `fitz.open(stream=…).page_count == 2`.
- `pdf_to_images` on that PDF at dpi=150 → assert 2 results, filenames
  `page_001.png`/`page_002.png`, and each opens as a PNG with the expected
  orientation (landscape/portrait preserved).
- DPI scaling: dpi=300 yields ~2× the pixel dimensions of dpi=150 (±a few px).
- JPG format: `fmt="jpg"` → filenames end `.jpg`, bytes decode as JPEG.

## File structure (additions)

```
tools/
├── pdf_convert/
│   └── pdf_converter.py     # images_to_pdf + pdf_to_images + CLI
├── server.py                # + /api/pdf/from-images, /api/pdf/to-images
├── index.html               # + 📄 PDF tab
├── pyproject.toml           # + pymupdf
└── test_pdf.py
```

## Out of scope

- Reordering pages in the UI (page order = queue order).
- Resolution/quality controls for image→PDF (images embedded as-is).
- OCR, PDF merging/splitting beyond the two directions above.
- This directory is not a git repository (no doc commit).
