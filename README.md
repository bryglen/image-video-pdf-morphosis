# Media Converter

A local web UI for converting images, videos, and PDFs. Powered by Pillow, FFmpeg, and PyMuPDF.

---

## Requirements

- Python 3.9+
- FFmpeg (for video conversion)
- Ghostscript (optional — best PDF compression; falls back to built-in if absent)

```bash
# macOS
brew install ffmpeg
brew install ghostscript   # optional, for best PDF compression
```

---

## Setup

Uses the venv from `image_convert/`:

```bash
cd image_convert
python3 -m venv .venv
source .venv/bin/activate
pip install pillow pillow-heif flask pymupdf
```

---

## Usage

```bash
./start.sh   # starts server at http://localhost:5002 and opens browser
./stop.sh    # stops the server
```

`start.sh` and `stop.sh` also sweep leftover temp files (see [Temp files](#temp-files)). Uploads up to 5 GB are accepted.

---

## Options that apply to every tab

- **Overwrite originals** (top-right toggle) — when checked, downloads drop the `_converted` suffix (e.g. `photo.jpg` instead of `photo_converted.jpg`). Choice persists across sessions.
- **Per-file Convert button** — every queued file has its own Convert button, so you can convert one file or re-convert after changing settings without removing and re-adding it. The button disables while that file is processing.
- **Dark / light theme** toggle (top-right), remembered across sessions.

---

## Image Converter

**Input:** HEIC, HEIF, AVIF, WebP, JPG, PNG, TIFF, BMP, GIF

**Output:** JPG, PNG, WebP, AVIF, TIFF, BMP, HEIC/HEIF

- Preserves EXIF metadata and ICC color profiles
- Alpha channels flattened to white when converting to JPG or BMP
- WebP lossless mode available
- Optional downscaling: Original, 4K, 1440p, 1080p, 720p, 480p (aspect ratio preserved, never upscales)

| Format | Notes |
|--------|-------|
| WebP (lossless) | Best size reduction for PNG/HEIC sources |
| AVIF | Smallest file sizes |
| HEIC | Smallest for photos |
| PNG | Safest for transparency |
| JPG | Near-lossless (q95) |
| TIFF | LZW compression, good for archival |

---

## Video Converter

**Input:** MP4, MOV, AVI, MKV, WebM, M4V

**Output:** MP4 (H.264), WebM (VP9), MOV (H.264)

- Selectable resolution: Original, 4K, 1440p, 1080p, 720p, 480p (aspect ratio preserved, never upscales; default Original / maintain)
- Playback speed: 0.5×, 1×, 1.25×, 1.5×, 2×, 2.5×
- Quality: Near-lossless, Balanced, Small (H.264 CRF 18/23/28; VP9/WebM CRF 20/33/43)
- **Hardware acceleration**: H.264 (MP4/MOV) auto-uses Apple VideoToolbox when available (much faster); falls back to libx264 otherwise. WebM/VP9 is always software-encoded.
- **iPhone / AirDrop compatible**: MP4 and MOV output is encoded `yuv420p` so it imports into Photos.
- Audio is synced with video speed; videos with no audio track are handled, and at 1× speed no needless speed re-encode is applied.
- Real conversion progress shown in the UI, with a **Cancel** button to abort an in-progress job (stops FFmpeg and discards the temp files).

---

## PDF Converter

**Images → PDF:** combine selected images into one multi-page PDF (queue order), or one PDF per image.

**PDF → Images:** render each PDF page to PNG or JPG at 72 / 150 / 300 DPI. Multi-page PDFs download as a ZIP; a single page downloads as the image.

**PDF → Pages:** export selected pages from a PDF into a new PDF. Pick pages by clicking thumbnails or typing a range (`1,3,5-7`) — the two stay in sync. Each PDF section has **All / None / Invert** buttons for quick selection. Output as one combined PDF, or one PDF per page (downloads as a ZIP when more than one). Pages are copied losslessly (real text/vectors preserved, not rasterized).

**Compress PDF:** shrink a PDF by quality preset — Small (72dpi) · Balanced (150dpi, default) · High (300dpi) — and/or an optional target size in MB (iterates quality down until the result fits). Uses **Ghostscript** when installed (best results, preserves text/vectors); otherwise falls back to a built-in PyMuPDF + Pillow path that re-renders pages (rasterizes — selectable text is lost). The UI reports which engine ran and the before → after size. For text-preserving compression without Ghostscript, install it: `brew install ghostscript`.

All PDF modes accept multiple PDFs at once: **Compress** and **PDF → Images** process each file independently (each gets its own download); **PDF → Pages** shows a section per PDF (independent page selection) and exports everything as one `pages.zip`.

- Image input includes HEIC/HEIF (via pillow-heif)
- PDF rendering powered by PyMuPDF

---

## CLI Tools

Each converter also has a standalone CLI tool:

```bash
source image_convert/.venv/bin/activate   # activate the venv for dependencies

# Image — batch convert a file or folder (prompts for format, resolution, etc.)
python3 image_convert/image_converter.py

# Video — compress / resize / speed-adjust a file or folder (prompts for format, quality, resolution, speed)
python3 video_convert/convert_video.py

# PDF — images<->pdf, pdf->images, extract pages, or compress (prompts for direction; 3 = extract pages, 4 = compress)
python3 pdf_convert/pdf_converter.py
```

---

## Project Structure

```
tools/
├── server.py               # Flask server (port 5002) — thin HTTP + progress layer
├── resolution.py           # shared resolution presets + compute_target_size
├── index.html              # Tabbed web UI
├── start.sh / stop.sh      # run/stop the server (also sweep temp files)
├── clean_temp.sh           # manually clear leftover converter temp dirs
├── tmp/                     # per-job temp files (auto-created, auto-swept)
├── pyproject.toml
├── image_convert/
│   └── image_converter.py  # image logic + CLI (shared with server.py)
├── video_convert/
│   └── convert_video.py    # video logic + CLI (shared with server.py)
└── pdf_convert/
    └── pdf_converter.py    # images<->pdf logic + CLI (shared with server.py)
```

---

## Temp files

Video conversion keeps each job's upload + output in a per-job folder under the project-local `tmp/` directory until you download it (cleaned 60s after download). To avoid leftovers from crashes or never-downloaded jobs:

- The server **sweeps `tmp/` on startup**.
- `start.sh` and `stop.sh` run the cleanup automatically.
- Run it manually any time: `./clean_temp.sh` (add `--dry-run` to preview, `-y` to skip the prompt). It also clears legacy orphans from the system temp dir.

Image and PDF conversion are in-memory (PDF compression uses a self-cleaning temp dir), so they leave nothing behind.
