# Image ⇄ PDF Converter Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 📄 PDF tab (web UI + CLI) that converts images → PDF (single combined or per-image) and PDF → images (PNG/JPG at a chosen DPI), via a shared `pdf_convert/pdf_converter.py` module.

**Architecture:** New shared module holds `images_to_pdf` (Pillow) and `pdf_to_images` (PyMuPDF). `server.py` exposes two routes that call it; `index.html` gets a third tab with a mode toggle. Same shared-module + repo-root-bootstrap pattern as the image/video converters.

**Tech Stack:** Python 3.9+, Flask, Pillow (+ pillow-heif), **PyMuPDF (`fitz`)** for PDF rendering, `zipfile` (stdlib), vanilla HTML/JS.

## Global Constraints

- New dependency: **PyMuPDF**, installed as `pymupdf`, imported as `import fitz`. Image→PDF uses only Pillow (already present).
- Module pattern: `pdf_convert/pdf_converter.py` = logic + CLI `main()`, with a `sys.path.insert(0, repo_root)` bootstrap and `register_heif_opener()` (so HEIC images convert to PDF). Mirrors `image_convert/image_converter.py`.
- Defaults: image→PDF Combine = ON; PDF→image format = PNG, DPI = 150. Multi-page PDF→images → ZIP; single page → the image directly. Page order = order added to the queue.
- PDF→image filenames: `page_001.<ext>`, 1-based, zero-padded to 3 digits; `<ext>` is `jpg` for jpg/jpeg, else `png`.
- Tests live at repo root, run from there with `python3 <test>.py`, plain `assert` + `__main__` runner — NO pytest.
- The project is **not** a git repository — each task ends with a verification checkpoint, not a commit (optional `git` commands apply only if you `git init` first).
- Run all `python3` commands from the repo root (`/Users/bryglen/Work/personal/tools`).

---

## File Structure

- Create: `pdf_convert/pdf_converter.py` — `images_to_pdf`, `pdf_to_images`, CLI.
- Create: `test_pdf.py` — root-level test runner.
- Modify: `server.py` — add `import zipfile`, import the pdf module, add 2 routes.
- Modify: `index.html` — add the 📄 PDF tab (button, panel, JS).
- Modify: `pyproject.toml` — add `pymupdf`.
- Modify: `README.md` — document the PDF tab + CLI.

---

## Task 1: PDF converter module + dependency

**Files:**
- Create: `pdf_convert/pdf_converter.py`
- Modify: `pyproject.toml`
- Test: `test_pdf.py`

**Interfaces:**
- Produces: `images_to_pdf(images: list[PIL.Image]) -> bytes`; `pdf_to_images(pdf_bytes: bytes, fmt="png", dpi=150) -> list[tuple[str, bytes]]`; constants `INPUT_IMAGE_EXTS`, `PDF_IMAGE_FORMATS`; `main()` CLI.

- [ ] **Step 1: Install the dependency**

Run: `python3 -m pip install pymupdf`
Then verify: `python3 -c "import fitz; print('pymupdf', fitz.VersionBind)"`
Expected: prints a version (e.g. `pymupdf 1.24.x`). If `pip` warns about an externally-managed environment, use `python3 -m pip install --user pymupdf`.

- [ ] **Step 2: Add the dependency to `pyproject.toml`**

Change the `dependencies` list so it reads exactly:

```toml
dependencies = [
    "pillow",
    "pillow-heif",
    "flask",
    "pymupdf"
]
```

- [ ] **Step 3: Write the failing test** — create `test_pdf.py`:

```python
"""Tests for pdf_convert.pdf_converter (needs pillow + pymupdf).
Run: python3 test_pdf.py"""

import io
import fitz
from PIL import Image
from pdf_convert.pdf_converter import images_to_pdf, pdf_to_images


def _img(w, h, color):
    return Image.new("RGB", (w, h), color)


def test_images_to_pdf_two_pages():
    pdf = images_to_pdf([_img(200, 100, (255, 0, 0)), _img(100, 200, (0, 0, 255))])
    assert pdf[:4] == b"%PDF"
    doc = fitz.open(stream=pdf, filetype="pdf")
    assert doc.page_count == 2
    doc.close()


def test_images_to_pdf_empty_raises():
    try:
        images_to_pdf([])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_pdf_to_images_roundtrip_png():
    pdf = images_to_pdf([_img(200, 100, (10, 20, 30)), _img(100, 200, (40, 50, 60))])
    out = pdf_to_images(pdf, fmt="png", dpi=150)
    assert len(out) == 2
    assert [n for n, _ in out] == ["page_001.png", "page_002.png"]
    p1 = Image.open(io.BytesIO(out[0][1]))
    p2 = Image.open(io.BytesIO(out[1][1]))
    assert p1.format == "PNG"
    assert p1.width > p1.height    # page 1 landscape
    assert p2.height > p2.width    # page 2 portrait


def test_pdf_to_images_dpi_scales():
    pdf = images_to_pdf([_img(200, 100, (10, 20, 30))])
    lo = Image.open(io.BytesIO(pdf_to_images(pdf, dpi=150)[0][1]))
    hi = Image.open(io.BytesIO(pdf_to_images(pdf, dpi=300)[0][1]))
    assert abs(hi.width - 2 * lo.width) <= 4


def test_pdf_to_images_jpg():
    pdf = images_to_pdf([_img(200, 100, (10, 20, 30))])
    out = pdf_to_images(pdf, fmt="jpg", dpi=150)
    assert out[0][0] == "page_001.jpg"
    assert Image.open(io.BytesIO(out[0][1])).format == "JPEG"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python3 test_pdf.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_convert.pdf_converter'`.

- [ ] **Step 5: Write the module** — create `pdf_convert/pdf_converter.py`:

```python
"""Image ⇄ PDF conversion logic + interactive batch CLI.

Imported by the web server (images_to_pdf, pdf_to_images) and runnable
standalone: python pdf_convert/pdf_converter.py
"""
import io
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from pillow_heif import register_heif_opener

# Repo-root importable regardless of cwd (consistency with the other modules).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

register_heif_opener()

INPUT_IMAGE_EXTS = {
    ".heic", ".heif", ".avif", ".webp", ".jpg", ".jpeg", ".png",
    ".tif", ".tiff", ".bmp", ".gif",
}
PDF_IMAGE_FORMATS = {"png", "jpg", "jpeg"}


def _to_rgb(img):
    """Flatten any image to RGB on white (PDF has no alpha channel)."""
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        alpha = img.getchannel("A") if "A" in img.getbands() else None
        bg.paste(img, mask=alpha)
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def images_to_pdf(images):
    """Combine a list of PIL Images into one multi-page PDF; return raw bytes."""
    if not images:
        raise ValueError("No images provided")
    pages = [_to_rgb(im) for im in images]
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


def pdf_to_images(pdf_bytes, fmt="png", dpi=150):
    """Render each PDF page to an image. Return [(filename, bytes), ...]."""
    fmt = (fmt or "png").lower()
    if fmt not in PDF_IMAGE_FORMATS:
        fmt = "png"
    ext = "jpg" if fmt in ("jpg", "jpeg") else "png"
    out_kind = "jpeg" if ext == "jpg" else "png"

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    results = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix)
            results.append((f"page_{i:03d}.{ext}", pix.tobytes(out_kind)))
    finally:
        doc.close()
    return results


# ── CLI ──────────────────────────────────────────────────────────────────────

FMT_CHOICES = ["png", "jpg"]
DPI_CHOICES = ["72", "150", "300"]


def ask_yes_no(prompt, default=False):
    suffix = " [Y/n]: " if default else " [y/N]: "
    ans = input(prompt + suffix).strip().lower()
    if not ans:
        return default
    return ans in {"y", "yes"}


def ask_choice(prompt, choices, default):
    while True:
        raw = input(f"{prompt} ({'/'.join(choices)}) [{default}]: ").strip().lower()
        if not raw:
            return default
        if raw in choices:
            return raw
        print("Invalid choice.")


def _collect_images(source):
    if source.is_file():
        return [source] if source.suffix.lower() in INPUT_IMAGE_EXTS else []
    return sorted(p for p in source.iterdir()
                  if p.is_file() and p.suffix.lower() in INPUT_IMAGE_EXTS)


def _images_to_pdf_cli(source, combine):
    files = _collect_images(source)
    if not files:
        print("No supported image files found.")
        return
    if combine:
        imgs = []
        for f in files:
            im = Image.open(f); im.load(); imgs.append(im)
        out = (source if source.is_dir() else source.parent) / "combined.pdf"
        out.write_bytes(images_to_pdf(imgs))
        print(f"✔ {len(files)} image(s) → {out}")
    else:
        for f in files:
            with Image.open(f) as im:
                im.load()
                data = images_to_pdf([im])
            out = f.with_name(f"{f.stem}_converted.pdf")
            out.write_bytes(data)
            print(f"✔ {f.name} → {out.name}")


def _pdf_to_images_cli(source, fmt, dpi):
    out_dir = source.with_suffix("")
    out_dir.mkdir(exist_ok=True)
    results = pdf_to_images(source.read_bytes(), fmt=fmt, dpi=dpi)
    for name, data in results:
        (out_dir / name).write_bytes(data)
    print(f"✔ {source.name} → {len(results)} image(s) in {out_dir}/")


def main():
    raw = input("Direction (1 = images→PDF, 2 = PDF→images): ").strip()
    if raw == "1":
        src = Path(input("Image file or folder path: ").strip().strip('"').strip("'")).expanduser()
        if not src.exists():
            print("Path not found."); return
        combine = ask_yes_no("Combine all images into one PDF?", default=True)
        _images_to_pdf_cli(src, combine)
    elif raw == "2":
        src = Path(input("PDF file path: ").strip().strip('"').strip("'")).expanduser()
        if not src.exists():
            print("Path not found."); return
        fmt = ask_choice("Output format", FMT_CHOICES, "png")
        dpi = int(ask_choice("DPI", DPI_CHOICES, "150"))
        _pdf_to_images_cli(src, fmt, dpi)
    else:
        print("Invalid direction.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python3 test_pdf.py`
Expected: PASS — `5 passed`.

- [ ] **Step 7: Checkpoint** — optional commit:
```bash
git add pdf_convert/pdf_converter.py test_pdf.py pyproject.toml
git commit -m "feat: PDF converter module (images<->pdf) + pymupdf dep"
```

---

## Task 2: server.py routes

**Files:**
- Modify: `server.py`

**Interfaces:**
- Consumes: `pdf_convert.pdf_converter.images_to_pdf`, `pdf_to_images`.

- [ ] **Step 1: Add imports**

In `server.py`, change the first import line to add `zipfile`:

```python
import io, sys, re, uuid, shutil, threading, subprocess, tempfile, zipfile
```

And after the line `from video_convert.convert_video import build_ffmpeg_cmd, VIDEO_MIME`, add:

```python
from pdf_convert.pdf_converter import images_to_pdf, pdf_to_images
```

- [ ] **Step 2: Add the two PDF routes**

Insert this block immediately BEFORE the `if __name__ == "__main__":` line at the bottom of `server.py`:

```python
# ── PDF ──────────────────────────────────────────────────────────────────────

@app.route("/api/pdf/from-images", methods=["POST"])
def pdf_from_images():
    files = request.files.getlist("file")
    if not files:
        return jsonify(error="No file provided"), 400

    try:
        before_size = 0
        images = []
        for f in files:
            raw = f.read()
            before_size += len(raw)
            im = Image.open(io.BytesIO(raw))
            im.load()
            images.append(im)

        data = images_to_pdf(images)
        after_size = len(data)

        if len(files) > 1:
            download_name = "combined.pdf"
        else:
            stem = Path(files[0].filename).stem if files[0].filename else "converted"
            download_name = f"{stem}_converted.pdf"

        response = send_file(
            io.BytesIO(data), mimetype="application/pdf",
            as_attachment=True, download_name=download_name,
        )
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["Access-Control-Expose-Headers"] = "X-Before-Size, X-After-Size"
        return response
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/pdf/to-images", methods=["POST"])
def pdf_to_images_route():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400

    file = request.files["file"]
    out_fmt = request.form.get("format", "png").lower()
    try:
        dpi = int(request.form.get("dpi", "150"))
    except ValueError:
        dpi = 150

    try:
        raw = file.read()
        before_size = len(raw)
        results = pdf_to_images(raw, fmt=out_fmt, dpi=dpi)
        if not results:
            return jsonify(error="PDF has no pages"), 500

        stem = Path(file.filename).stem if file.filename else "pdf"

        if len(results) == 1:
            name, data = results[0]
            ext = name.rsplit(".", 1)[-1]
            mime = "image/jpeg" if ext == "jpg" else "image/png"
            payload, after_size = io.BytesIO(data), len(data)
            download_name = f"{stem}_{name}"
        else:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in results:
                    zf.writestr(name, data)
            after_size = payload.getbuffer().nbytes
            payload.seek(0)
            mime = "application/zip"
            download_name = f"{stem}_pages.zip"

        response = send_file(payload, mimetype=mime, as_attachment=True,
                             download_name=download_name)
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["Access-Control-Expose-Headers"] = "X-Before-Size, X-After-Size"
        return response
    except Exception as e:
        return jsonify(error=str(e)), 500
```

- [ ] **Step 3: Smoke-test both routes**

Run from the repo root:
```bash
python3 - <<'PY'
import io, zipfile
from PIL import Image
import server
c = server.app.test_client()

# images -> combined pdf (2 files in one request)
def png(w, h):
    b = io.BytesIO(); Image.new("RGB", (w, h), (1, 2, 3)).save(b, "PNG"); b.seek(0); return b
r = c.post("/api/pdf/from-images",
           data={"file": [(png(200, 100), "a.png"), (png(100, 200), "b.png")]},
           content_type="multipart/form-data")
print("from-images status", r.status_code, "ct", r.headers["Content-Type"])
assert r.status_code == 200 and r.data[:4] == b"%PDF"
pdf_bytes = r.data

# that pdf -> images (2 pages -> zip)
r2 = c.post("/api/pdf/to-images",
            data={"format": "png", "dpi": "150", "file": (io.BytesIO(pdf_bytes), "doc.pdf")},
            content_type="multipart/form-data")
print("to-images status", r2.status_code, "ct", r2.headers["Content-Type"])
assert r2.status_code == 200
zf = zipfile.ZipFile(io.BytesIO(r2.data))
print("zip members", zf.namelist())
assert zf.namelist() == ["page_001.png", "page_002.png"]
print("OK")
PY
```
Expected: `from-images status 200` (PDF), `to-images status 200` (zip), `zip members ['page_001.png', 'page_002.png']`, `OK`.

- [ ] **Step 4: Checkpoint** — optional commit:
```bash
git add server.py
git commit -m "feat: server PDF routes (from-images, to-images)"
```

---

## Task 3: index.html — the 📄 PDF tab

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add the tab button**

In the `.tabs` block, after `<button class="tab-btn" data-tab="video">&#127916; Video</button>`, add:

```html
  <button class="tab-btn" data-tab="pdf">&#128196; PDF</button>
```

- [ ] **Step 2: Add the tab panel**

Immediately AFTER the closing `</div>` of the VIDEO tab panel (`<div id="tab-video" class="tab-panel">…</div>`) and BEFORE `<script>`, insert:

```html
<!-- PDF TAB -->
<div id="tab-pdf" class="tab-panel">
  <div class="card">
    <div class="options-row">
      <span class="option-label">Mode</span>
      <div class="fmt-group" id="pdfModeGroup">
        <button class="fmt-btn active" data-mode="img2pdf">Images &#8594; PDF</button>
        <button class="fmt-btn" data-mode="pdf2img">PDF &#8594; Images</button>
      </div>
    </div>

    <div class="drop-zone" id="pdfDropZone">
      <input type="file" id="pdfFileInput" multiple accept="image/*,.heic,.heif" />
      <div class="drop-icon">&#128196;</div>
      <div class="drop-label" id="pdfDropLabel">Drop images here or click to browse</div>
      <div class="drop-hint" id="pdfDropHint">Combine images into a PDF</div>
    </div>

    <div class="options-row" id="pdfImgOpts">
      <span class="option-label">Output</span>
      <label class="lossless-wrap visible" id="pdfCombineWrap">
        <input type="checkbox" id="pdfCombineCheck" checked />
        Combine into one PDF
      </label>
    </div>

    <div class="options-row" id="pdfFmtRow" style="display:none">
      <span class="option-label">Format</span>
      <div class="fmt-group" id="pdfFmtGroup">
        <button class="fmt-btn active" data-fmt="png">PNG</button>
        <button class="fmt-btn" data-fmt="jpg">JPG</button>
      </div>
    </div>

    <div class="options-row" id="pdfDpiRow" style="display:none">
      <span class="option-label">DPI</span>
      <div class="fmt-group" id="pdfDpiGroup">
        <button class="fmt-btn" data-dpi="72">72</button>
        <button class="fmt-btn active" data-dpi="150">150</button>
        <button class="fmt-btn" data-dpi="300">300</button>
      </div>
    </div>

    <div class="queue" id="pdfQueue" style="display:none">
      <div class="queue-header">
        <span class="queue-title">Files</span>
        <button class="convert-all-btn" id="pdfConvertAllBtn">Convert</button>
      </div>
      <div class="file-list" id="pdfFileList"></div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add the tab's JavaScript**

At the END of the `<script>` block (immediately before `</script>`), append:

```javascript
// ── PDF converter ────────────────────────────────────────────────────────────
const pdfDropZone   = document.getElementById('pdfDropZone');
const pdfFileInput  = document.getElementById('pdfFileInput');
const pdfDropLabel  = document.getElementById('pdfDropLabel');
const pdfDropHint   = document.getElementById('pdfDropHint');
const pdfQueue      = document.getElementById('pdfQueue');
const pdfFileList   = document.getElementById('pdfFileList');
const pdfConvertBtn = document.getElementById('pdfConvertAllBtn');
const pdfImgOpts    = document.getElementById('pdfImgOpts');
const pdfFmtRow     = document.getElementById('pdfFmtRow');
const pdfDpiRow     = document.getElementById('pdfDpiRow');
const pdfCombineCheck = document.getElementById('pdfCombineCheck');

let pdfMode = 'img2pdf', pdfFmt = 'png', pdfDpi = '150';
let pdfFiles = [], pdfNextId = 0;

makeOptionPicker(document.getElementById('pdfFmtGroup'), btn => { pdfFmt = btn.dataset.fmt; });
makeOptionPicker(document.getElementById('pdfDpiGroup'), btn => { pdfDpi = btn.dataset.dpi; });

makeOptionPicker(document.getElementById('pdfModeGroup'), btn => {
  pdfMode = btn.dataset.mode;
  const img = pdfMode === 'img2pdf';
  pdfImgOpts.style.display = img ? '' : 'none';
  pdfFmtRow.style.display  = img ? 'none' : '';
  pdfDpiRow.style.display  = img ? 'none' : '';
  pdfFileInput.accept = img ? 'image/*,.heic,.heif' : 'application/pdf,.pdf';
  pdfDropLabel.textContent = img ? 'Drop images here or click to browse' : 'Drop a PDF here or click to browse';
  pdfDropHint.textContent  = img ? 'Combine images into a PDF' : 'Each page becomes an image';
  pdfClearAll();
});

pdfDropZone.addEventListener('dragover',  e => { e.preventDefault(); pdfDropZone.classList.add('drag-over'); });
pdfDropZone.addEventListener('dragleave', () => pdfDropZone.classList.remove('drag-over'));
pdfDropZone.addEventListener('drop', e => { e.preventDefault(); pdfDropZone.classList.remove('drag-over'); pdfAddFiles([...e.dataTransfer.files]); });
pdfFileInput.addEventListener('change', () => { pdfAddFiles([...pdfFileInput.files]); pdfFileInput.value = ''; });

function pdfClearAll() {
  pdfFiles = [];
  pdfFileList.innerHTML = '';
  pdfQueue.style.display = 'none';
}

function pdfAddFiles(fs) {
  if (pdfMode === 'pdf2img') { pdfClearAll(); fs = fs.slice(-1); }  // one PDF at a time
  fs.forEach(f => {
    const id = pdfNextId++;
    pdfFiles.push({ id, file: f, done: false });
    pdfRenderItem(pdfFiles.at(-1));
  });
  pdfQueue.style.display = pdfFiles.length ? '' : 'none';
}

function pdfRenderItem(item) {
  const el = document.createElement('div');
  el.className = 'file-item'; el.id = `pdf-item-${item.id}`;
  const thumb = item.file.type.startsWith('image/')
    ? `<img class="file-thumb" src="${URL.createObjectURL(item.file)}" alt="" />`
    : `<div class="file-icon">&#128196;</div>`;
  el.innerHTML = `
    ${thumb}
    <div class="file-info">
      <div class="file-name">${item.file.name}</div>
      <div class="file-meta" id="pdf-meta-${item.id}">${fmtSize(item.file.size)}</div>
    </div>
    <span class="file-status status-pending" id="pdf-st-${item.id}">Pending</span>
    <button class="remove-btn" data-id="${item.id}">&#x2715;</button>`;
  el.querySelector('.remove-btn').addEventListener('click', () => pdfRemove(item.id));
  pdfFileList.appendChild(el);
}

function pdfRemove(id) {
  pdfFiles = pdfFiles.filter(f => f.id !== id);
  document.getElementById(`pdf-item-${id}`)?.remove();
  if (!pdfFiles.length) pdfQueue.style.display = 'none';
}

function pdfSetStatus(id, cls, text) {
  const el = document.getElementById(`pdf-st-${id}`);
  if (el) { el.className = `file-status status-${cls}`; el.textContent = text; }
}

function pdfDownloadLink(id, blob, name) {
  const a = Object.assign(document.createElement('a'), {
    className: 'dl-btn', href: URL.createObjectURL(blob), download: name, textContent: 'Download',
  });
  const st = document.getElementById(`pdf-st-${id}`);
  if (st) { st.innerHTML = ''; st.appendChild(a); }
}

async function pdfConvertCombined() {
  const pending = pdfFiles.filter(f => !f.done);
  if (!pending.length) return;
  pending.forEach(f => pdfSetStatus(f.id, 'working', 'Converting…'));
  const form = new FormData();
  pending.forEach(f => form.append('file', f.file));
  try {
    const res = await fetch('/api/pdf/from-images', { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      pending.forEach(f => pdfSetStatus(f.id, 'error', err.error || 'Failed'));
      return;
    }
    const blob = await res.blob();
    pending.forEach((f, i) => {
      f.done = true;
      if (i === 0) pdfDownloadLink(f.id, blob, 'combined.pdf');
      else pdfSetStatus(f.id, 'pending', 'In PDF');
    });
  } catch {
    pending.forEach(f => pdfSetStatus(f.id, 'error', 'Failed'));
  }
}

async function pdfConvertOne(item) {
  pdfSetStatus(item.id, 'working', 'Converting…');
  const form = new FormData();
  form.append('file', item.file);
  let url, name = null;
  if (pdfMode === 'img2pdf') {
    url = '/api/pdf/from-images';
    name = item.file.name.replace(/\.[^.]+$/, '') + '_converted.pdf';
  } else {
    url = '/api/pdf/to-images';
    form.append('format', pdfFmt);
    form.append('dpi', pdfDpi);
  }
  try {
    const res = await fetch(url, { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      pdfSetStatus(item.id, 'error', err.error || 'Failed');
      return;
    }
    const blob = await res.blob();
    item.done = true;
    if (!name) {
      const stem = item.file.name.replace(/\.[^.]+$/, '');
      name = blob.type === 'application/zip' ? `${stem}_pages.zip` : `${stem}_page.${pdfFmt}`;
    }
    pdfDownloadLink(item.id, blob, name);
  } catch {
    pdfSetStatus(item.id, 'error', 'Failed');
  }
}

pdfConvertBtn.addEventListener('click', async () => {
  if (!pdfFiles.filter(f => !f.done).length) return;
  pdfConvertBtn.disabled = true;
  if (pdfMode === 'img2pdf' && pdfCombineCheck.checked) {
    await pdfConvertCombined();
  } else {
    for (const item of pdfFiles.filter(f => !f.done)) await pdfConvertOne(item);
  }
  pdfConvertBtn.disabled = false;
});
```

- [ ] **Step 4: Verify the additions**

Run from the repo root:
```bash
grep -c 'data-tab="pdf"' index.html        # expect 1
grep -c 'id="tab-pdf"' index.html           # expect 1
grep -c 'id="pdfModeGroup"' index.html      # expect 1
grep -c "fetch('/api/pdf/from-images'" index.html   # expect 2
grep -c "fetch('/api/pdf/to-images'" index.html     # expect 1
grep -c 'id="pdfConvertAllBtn"' index.html  # expect 2 (HTML + JS getElementById)
```

- [ ] **Step 5: Manual UI check**

`./start.sh` → http://localhost:5002 → 📄 PDF tab:
1. Images→PDF, Combine ON: drop 2+ images → Convert → one `combined.pdf` downloads and opens with one page per image.
2. Images→PDF, Combine OFF: each image gets its own Download (separate PDFs).
3. PDF→Images: switch mode, drop the PDF from step 1, format=PNG, DPI=150 → Convert → a `*_pages.zip` downloads containing `page_001.png`, `page_002.png`.
Then `./stop.sh`.

- [ ] **Step 6: Checkpoint** — optional commit:
```bash
git add index.html
git commit -m "feat: 📄 PDF tab (images<->pdf) in the web UI"
```

---

## Task 4: README + full verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the PDF converter**

In `README.md`, after the `## Video Converter` section (before `## CLI Tools`), add:

```markdown
---

## PDF Converter

**Images → PDF:** combine selected images into one multi-page PDF (queue order), or one PDF per image.

**PDF → Images:** render each PDF page to PNG or JPG at 72 / 150 / 300 DPI. Multi-page PDFs download as a ZIP; a single page downloads as the image.

- Image input includes HEIC/HEIF (via pillow-heif)
- PDF rendering powered by PyMuPDF
```

In the **CLI Tools** code block, add:

```bash
# PDF — images<->pdf, batch over a file or folder
python3 pdf_convert/pdf_converter.py
```

In **Project Structure**, add under the tree (after the `video_convert/` entry):

```
└── pdf_convert/
    └── pdf_converter.py    # images<->pdf logic + CLI (shared with server.py)
```

And add `pymupdf` to the requirements note if one is listed.

- [ ] **Step 2: Run the full automated suite**

Run from the repo root:
```bash
python3 test_resolution.py | tail -1
python3 test_image.py | tail -1
python3 test_video.py | tail -1
python3 test_pdf.py | tail -1
python3 -c "import server; print('server import OK')"
```
Expected: `10 passed`, `3 passed`, `9 passed`, `5 passed`, `server import OK`.

- [ ] **Step 3: Final end-to-end check**

`./start.sh`, exercise the PDF tab per Task 3 Step 5 (both directions), confirm downloads are correct, then `./stop.sh`. Run `python3 pdf_convert/pdf_converter.py` once in each direction against sample files and confirm the outputs.

- [ ] **Step 4: Checkpoint** — optional commit:
```bash
git add README.md
git commit -m "docs: document the PDF converter tab + CLI"
```

---

## Notes for the implementer

- `pix.tobytes("jpeg")` / `pix.tobytes("png")` are the PyMuPDF pixmap encoders; do not pass `"jpg"` to `tobytes` (use `"jpeg"`), but the output *filename* extension is `jpg`.
- `request.files.getlist("file")` returns all parts named `file` — that's how the combined Images→PDF request carries multiple images in one POST.
- Image→PDF embeds images at their pixel size; there is intentionally no resolution/quality control (out of scope).
