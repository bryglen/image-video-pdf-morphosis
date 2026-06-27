# PDF Compress — Design

**Date:** 2026-06-24
**Status:** Approved

## Summary

Add a fourth PDF mode, **Compress**, to the Media Converter. The user drops a PDF, picks a
quality preset (Small / Balanced / High) and optionally types a target size in MB, and gets
back a smaller PDF. Compression uses **Ghostscript when available** (best results, preserves
text/vectors) and falls back to a **pure-Python** path (PyMuPDF + Pillow) when `gs` is absent
or errors.

## Goals

- Shrink a PDF (e.g. 8 MB → ~3 MB) from the web UI and the CLI.
- Quality presets as the default control; an optional target-size box that iterates to fit.
- Zero mandatory new dependencies (Ghostscript is optional; Python fallback always works).

## Non-Goals (YAGNI)

- Live progress bar (compression is synchronous, a few seconds; the target ladder is bounded).
- Per-image or per-page quality control.
- Lossless-only compression guarantees (the Python fallback rasterizes by design).

## Engine Strategy

- **Ghostscript (primary):** detected via `shutil.which("gs")`. Preserves text and vectors.
- **Python fallback (secondary):** used when `gs` is absent **or** the `gs` run fails. Renders
  each page to a JPEG at the chosen DPI/quality and rebuilds the PDF. Reliable size control,
  but **rasterizes** (selectable text is lost). The UI surfaces which engine ran and hints to
  install Ghostscript (`brew install ghostscript`) when the fallback can't meet the target.

## Components (`pdf_convert/pdf_converter.py`)

### Presets and ladder

```python
COMPRESS_PRESETS = {
    "small":    {"gs": "/screen",  "dpi": 72,  "q": 50},
    "balanced": {"gs": "/ebook",   "dpi": 150, "q": 70},   # default
    "high":     {"gs": "/printer", "dpi": 300, "q": 85},
}
TARGET_LADDER = [(200, 80), (150, 70), (120, 65), (100, 60), (72, 50), (50, 40)]  # (dpi, jpeg_q), high→low
```

### Functions

1. **`gs_available() -> bool`** — `shutil.which("gs") is not None`.

2. **`_compress_with_ghostscript(pdf_bytes, dpi, jpeg_quality) -> bytes`**
   - Writes input to a temp file, runs Ghostscript to a temp output, returns the bytes.
   - Command:
     `gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.4 -dPDFSETTINGS=/ebook
      -dDownsampleColorImages=true -dColorImageResolution=<dpi>
      -dDownsampleGrayImages=true -dGrayImageResolution=<dpi>
      -dDownsampleMonoImages=true -dMonoImageResolution=<dpi>
      -dNOPAUSE -dQUIET -dBATCH -sOutputFile=<out> <in>`
   - Raises `RuntimeError` on non-zero exit / missing output. (`jpeg_quality` accepted for a
     uniform signature; Ghostscript manages its own image quality, so it is not forwarded.)

3. **`_compress_with_python(pdf_bytes, dpi, jpeg_quality) -> bytes`**
   - For each page: render to an RGB pixmap at `dpi` (`alpha=False`), encode to JPEG at
     `jpeg_quality` via Pillow, insert into a new page sized to the original page rectangle.
   - Returns `out.tobytes(garbage=4, deflate=True)`.

4. **`compress_pdf(pdf_bytes, quality="balanced", target_bytes=None) -> (bytes, str)`**
   - Returns `(data, engine)` where `engine` is the one that actually produced the output
     (`"ghostscript"` | `"python"`), so the caller can report it accurately even after a
     fallback.
   - Chooses runner: Ghostscript if `gs_available()`, else Python. If the Ghostscript runner
     raises, retries once with the Python runner and reports `"python"`.
   - **No target:** look up the preset, run one pass at its `dpi`/`q`.
   - **With target:** if `len(pdf_bytes) <= target_bytes`, return `(pdf_bytes, engine)`
     unchanged (where `engine` reflects the runner that would have run). Otherwise walk
     `TARGET_LADDER` high→low, returning the first result `<= target_bytes` (the highest-quality
     fit); if none fit, return the smallest (last) result.

## Route (`server.py`)

**`POST /api/pdf/compress`** — multipart `file`, form `quality` (`small`|`balanced`|`high`,
default `balanced`), optional form `target_mb` (float).
- Parses `target_mb` → `target_bytes` (`None` if blank/invalid/≤0).
- Calls `compress_pdf`, returns the PDF as an attachment `<stem>_compressed.pdf`.
- Headers: `X-Before-Size`, `X-After-Size`, and `X-Compress-Engine` (`ghostscript`|`python`,
  the engine actually returned by `compress_pdf`), all exposed via
  `Access-Control-Expose-Headers`.
- Errors → `{error}` with 500.

## UI (`index.html`)

Add a fourth mode button to the PDF mode toggle: **Compress**.

When **Compress** is active:

```
┌─────────────────────────────────────────────┐
│  Drop a PDF here or click to browse           │
└─────────────────────────────────────────────┘

Quality:     ( Small ) ( • Balanced ) ( High )
Target size: [   ] MB   (optional)

[ Compress ]      then:  report.pdf  8.0 MB → 2.9 MB (64% smaller) · Ghostscript
```

- One PDF at a time (like PDF → Images).
- Quality preset group reuses the existing `.fmt-btn` option-picker; default Balanced.
- Optional numeric "Target size (MB)" input. When filled it drives the result; when blank the
  preset alone is used.
- On success, the file row shows before → after size, percent saved, and the engine used.
  When the engine is `python` and the result still exceeds the target, append a hint to install
  Ghostscript for better, text-preserving compression.

## Data Flow

```
Drop PDF → pick preset (+ optional target MB) → Compress
  → POST /api/pdf/compress (file, quality, target_mb?)
  ← <stem>_compressed.pdf + X-Before-Size / X-After-Size / X-Compress-Engine
```

Stateless: the browser holds the File and sends it on the one request.

## Error Handling

- Corrupt / non-PDF upload → exception → `{error}` 500.
- Ghostscript run failure → automatic Python fallback inside `compress_pdf`.
- Blank/invalid `target_mb` → treated as no target (preset-only).

## Testing (`test_pdf.py`)

- `gs_available()` returns a bool.
- `_compress_with_python` on an image-heavy test PDF: output is a valid PDF, same page count,
  and smaller than the input.
- `compress_pdf(..., target_bytes=...)`: the returned `data` is `<= target` when achievable
  (Python path on a synthetic large PDF); the returned `data` **is the original object
  unchanged** (identity) when input is already under target; the returned `engine` is a valid
  label.
- Each preset (`small`/`balanced`/`high`) runs via `compress_pdf` without error and yields a
  valid PDF.
- Ghostscript path is exercised only when `gs_available()` is true (skipped on machines without
  `gs`).

## CLI (parity)

Extend `pdf_convert/pdf_converter.py`'s `main()` with direction `4 = compress PDF`: prompt for
PDF path, quality preset, and optional target MB; write `<stem>_compressed.pdf` next to the
source and print before/after sizes and the engine used.
