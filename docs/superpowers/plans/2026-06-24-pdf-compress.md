# PDF Compress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Compress" PDF mode that shrinks a PDF via Ghostscript (preferred) or a pure-Python fallback, by quality preset and/or an optional target size.

**Architecture:** All compression logic lives in `pdf_convert/pdf_converter.py` (pure functions, unit-tested in `test_pdf.py`, shared with the CLI). `server.py` adds one thin, stateless route. `index.html` gains a fourth PDF mode with a quality preset toggle and an optional target-size input.

**Tech Stack:** Python 3.9+, Flask, PyMuPDF (`fitz`), Pillow; optional external `gs` (Ghostscript); vanilla HTML/CSS/JS.

## Global Constraints

- **Ghostscript is optional, never required.** Detect with `shutil.which("gs")`; the Python fallback must always work with the existing deps (PyMuPDF + Pillow).
- **Engine reported accurately.** `compress_pdf` returns the engine that actually produced the output (`"ghostscript"` | `"python"`), including after a fallback.
- **Server is stateless.** Browser holds the `File` and sends bytes on the one request.
- **`index.html` stays self-contained.** No external JS libraries.
- **Presets:** `small` → (`/screen`, 72dpi, q50), `balanced` → (`/ebook`, 150dpi, q70, default), `high` → (`/printer`, 300dpi, q85).
- **Target ladder (dpi, jpeg_q), high→low:** `[(200,80),(150,70),(120,65),(100,60),(72,50),(50,40)]`.
- **Test style:** plain `test_*` functions with bare `assert`s in `test_pdf.py`; no pytest. `__main__` auto-discovers them. Tests must not require `gs` (the `gs` path test self-skips when `gs` is absent).
- **This directory is NOT a git repository.** End-of-task checkpoint is running `python3 test_pdf.py`, not a commit.
- **Environment for all commands:** run from repo root with the venv active:
  ```bash
  cd /Users/bryglen/Work/personal/tools
  source image_convert/.venv/bin/activate
  ```

---

### Task 1: `gs_available` + `_compress_with_python` + presets/ladder constants

**Files:**
- Modify: `pdf_convert/pdf_converter.py` (imports near top; constants + functions after `extract_pdf_pages`, before the CLI banner)
- Test: `test_pdf.py`

**Interfaces:**
- Consumes: nothing from earlier work.
- Produces:
  - `COMPRESS_PRESETS: dict` and `TARGET_LADDER: list[tuple[int,int]]` (module constants).
  - `gs_available() -> bool`.
  - `_compress_with_python(pdf_bytes: bytes, dpi: int, jpeg_quality: int) -> bytes` — renders each page to a JPEG at `dpi`/`jpeg_quality` and rebuilds the PDF (rasterizes).

- [ ] **Step 1: Write the failing tests**

Add `gs_available, _compress_with_python` to the import in `test_pdf.py`. Add a noisy-PDF fixture helper and tests:

```python
def _noisy_pdf(pages=2, size=800):
    """A multi-page PDF whose pages are high-quality JPEGs of noise (poorly compressible)."""
    doc = fitz.open()
    for _ in range(pages):
        noise = Image.effect_noise((size, size), 90).convert("RGB")
        buf = io.BytesIO()
        noise.save(buf, format="JPEG", quality=95)
        page = doc.new_page(width=size, height=size)
        page.insert_image(page.rect, stream=buf.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def test_gs_available_returns_bool():
    assert isinstance(gs_available(), bool)


def test_compress_with_python_shrinks_and_preserves_pages():
    src = _noisy_pdf(pages=2)
    out = _compress_with_python(src, dpi=50, jpeg_quality=40)
    assert out[:4] == b"%PDF"
    assert len(out) < len(src)
    doc = fitz.open(stream=out, filetype="pdf")
    assert doc.page_count == 2
    doc.close()


def test_compress_with_python_dpi_monotonic():
    src = _noisy_pdf(pages=1)
    lo = _compress_with_python(src, dpi=50, jpeg_quality=40)
    mid = _compress_with_python(src, dpi=150, jpeg_quality=70)
    assert len(lo) < len(mid)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_pdf.py`
Expected: FAIL — `ImportError: cannot import name 'gs_available'`.

- [ ] **Step 3: Write the implementation**

In `pdf_convert/pdf_converter.py`, extend the top imports (the file currently imports `io`, `sys`, `Path`, `fitz`, `Image`, `register_heif_opener`). Add:

```python
import shutil
import subprocess
import tempfile
```

Then add, after `extract_pdf_pages` and before the `# ── CLI ──` banner:

```python
COMPRESS_PRESETS = {
    "small":    {"gs": "/screen",  "dpi": 72,  "q": 50},
    "balanced": {"gs": "/ebook",   "dpi": 150, "q": 70},
    "high":     {"gs": "/printer", "dpi": 300, "q": 85},
}
TARGET_LADDER = [(200, 80), (150, 70), (120, 65), (100, 60), (72, 50), (50, 40)]


def gs_available():
    """True if the Ghostscript 'gs' binary is on PATH."""
    return shutil.which("gs") is not None


def _compress_with_python(pdf_bytes, dpi, jpeg_quality):
    """Fallback: render each page to a JPEG at dpi/quality and rebuild the PDF.

    Reliable size control but rasterizes (selectable text is lost).
    """
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = fitz.open()
    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for page in src:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=jpeg_quality)
            rect = page.rect
            newpage = out.new_page(width=rect.width, height=rect.height)
            newpage.insert_image(rect, stream=buf.getvalue())
        return out.tobytes(garbage=4, deflate=True)
    finally:
        src.close()
        out.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_pdf.py`
Expected: PASS — the three new tests print `ok`.

- [ ] **Step 5: Checkpoint**

Run: `python3 test_pdf.py`
Expected: all tests `ok`, 0 failures.

---

### Task 2: `_compress_with_ghostscript`

**Files:**
- Modify: `pdf_convert/pdf_converter.py` (add function after `_compress_with_python`)
- Test: `test_pdf.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_compress_with_ghostscript(pdf_bytes: bytes, dpi: int, jpeg_quality: int) -> bytes` — runs `gs` to a temp file and returns the bytes. Raises `RuntimeError` on failure. (`jpeg_quality` accepted for a uniform signature with the Python runner; Ghostscript manages its own image quality and does not use it.)

- [ ] **Step 1: Write the failing test**

Add `_compress_with_ghostscript` to the import in `test_pdf.py`. Add a self-skipping test:

```python
def test_compress_with_ghostscript_when_available():
    if not gs_available():
        print("    (skipped: gs not installed)")
        return
    src = _noisy_pdf(pages=2)
    out = _compress_with_ghostscript(src, dpi=72, jpeg_quality=50)
    assert out[:4] == b"%PDF"
    doc = fitz.open(stream=out, filetype="pdf")
    assert doc.page_count == 2
    doc.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_pdf.py`
Expected: FAIL — `ImportError: cannot import name '_compress_with_ghostscript'`.

- [ ] **Step 3: Write the implementation**

Add to `pdf_convert/pdf_converter.py` after `_compress_with_python`:

```python
def _compress_with_ghostscript(pdf_bytes, dpi, jpeg_quality):
    """Compress via Ghostscript (preserves text/vectors). Raises RuntimeError on failure."""
    with tempfile.TemporaryDirectory() as d:
        inp = Path(d) / "in.pdf"
        outp = Path(d) / "out.pdf"
        inp.write_bytes(pdf_bytes)
        cmd = [
            "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook",
            "-dDownsampleColorImages=true", f"-dColorImageResolution={dpi}",
            "-dDownsampleGrayImages=true",  f"-dGrayImageResolution={dpi}",
            "-dDownsampleMonoImages=true",  f"-dMonoImageResolution={dpi}",
            "-dNOPAUSE", "-dQUIET", "-dBATCH",
            f"-sOutputFile={outp}", str(inp),
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0 or not outp.exists():
            msg = proc.stderr.decode("utf-8", "replace")[:200]
            raise RuntimeError(f"Ghostscript failed: {msg}")
        return outp.read_bytes()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_pdf.py`
Expected: PASS — `test_compress_with_ghostscript_when_available` prints `ok` (with `(skipped: gs not installed)` on machines without `gs`).

- [ ] **Step 5: Checkpoint**

Run: `python3 test_pdf.py`
Expected: all tests `ok`, 0 failures.

---

### Task 3: `compress_pdf` orchestrator

**Files:**
- Modify: `pdf_convert/pdf_converter.py` (add function after `_compress_with_ghostscript`)
- Test: `test_pdf.py`

**Interfaces:**
- Consumes: `gs_available`, `_compress_with_python`, `_compress_with_ghostscript`, `COMPRESS_PRESETS`, `TARGET_LADDER`.
- Produces: `compress_pdf(pdf_bytes: bytes, quality: str = "balanced", target_bytes: int | None = None) -> tuple[bytes, str]` — returns `(data, engine)`.

- [ ] **Step 1: Write the failing tests**

Add `compress_pdf` to the import in `test_pdf.py`. Add:

```python
def test_compress_pdf_preset_returns_valid_pdf():
    src = _noisy_pdf(pages=1)
    for q in ("small", "balanced", "high"):
        data, engine = compress_pdf(src, quality=q)
        assert data[:4] == b"%PDF"
        assert engine in ("ghostscript", "python")


def test_compress_pdf_target_met_when_achievable():
    src = _noisy_pdf(pages=2)            # ~1+ MB of noise
    target = 120 * 1024                  # 120 KB — reachable by the low end of the ladder
    data, engine = compress_pdf(src, target_bytes=target)
    assert len(data) <= target
    assert engine in ("ghostscript", "python")


def test_compress_pdf_returns_original_when_already_under_target():
    src = _noisy_pdf(pages=1)
    data, engine = compress_pdf(src, target_bytes=len(src) + 1000)
    assert data is src                   # identity: untouched
    assert engine in ("ghostscript", "python")


def test_compress_pdf_unknown_quality_falls_back_to_balanced():
    src = _noisy_pdf(pages=1)
    data, _ = compress_pdf(src, quality="bogus")
    assert data[:4] == b"%PDF"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_pdf.py`
Expected: FAIL — `ImportError: cannot import name 'compress_pdf'`.

- [ ] **Step 3: Write the implementation**

Add to `pdf_convert/pdf_converter.py` after `_compress_with_ghostscript`:

```python
def compress_pdf(pdf_bytes, quality="balanced", target_bytes=None):
    """Compress a PDF. Returns (data, engine) where engine is "ghostscript" or "python".

    With no target_bytes, runs one pass at the preset's dpi/quality.
    With target_bytes, returns the highest-quality ladder result that fits (<= target),
    or the smallest result if none fit, or the original unchanged if already under target.
    Ghostscript is used when available; on its failure (or absence) the Python path runs.
    """
    if quality not in COMPRESS_PRESETS:
        quality = "balanced"
    use_gs = gs_available()
    state = {"engine": "ghostscript" if use_gs else "python"}

    def run(dpi, q):
        if use_gs:
            try:
                data = _compress_with_ghostscript(pdf_bytes, dpi, q)
                state["engine"] = "ghostscript"
                return data
            except Exception:
                pass  # fall through to Python on any gs failure
        state["engine"] = "python"
        return _compress_with_python(pdf_bytes, dpi, q)

    if target_bytes is not None:
        if len(pdf_bytes) <= target_bytes:
            return pdf_bytes, state["engine"]
        last = None
        for dpi, q in TARGET_LADDER:
            last = run(dpi, q)
            if len(last) <= target_bytes:
                return last, state["engine"]
        return last, state["engine"]

    preset = COMPRESS_PRESETS[quality]
    return run(preset["dpi"], preset["q"]), state["engine"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_pdf.py`
Expected: PASS — the four new tests print `ok`.

- [ ] **Step 5: Checkpoint**

Run: `python3 test_pdf.py`
Expected: all tests `ok`, 0 failures. This completes the logic layer.

---

### Task 4: Flask route `/api/pdf/compress`

**Files:**
- Modify: `server.py` (extend the PDF import on lines 8-11; add a route after `pdf_extract_route`, before `if __name__ == "__main__":`)

**Interfaces:**
- Consumes: `compress_pdf` from `pdf_convert.pdf_converter`.
- Produces (HTTP): `POST /api/pdf/compress` (multipart `file`, form `quality`, optional form `target_mb`) → a `<stem>_compressed.pdf` with headers `X-Before-Size`, `X-After-Size`, `X-Compress-Engine`.

- [ ] **Step 1: Extend the import**

In `server.py`, update the PDF import block (added in the page-export work) to include the compress functions:

```python
from pdf_convert.pdf_converter import (
    images_to_pdf, pdf_to_images,
    parse_page_ranges, pdf_page_count, pdf_thumbnails, extract_pdf_pages,
    compress_pdf,
)
```

- [ ] **Step 2: Add the route**

Insert into `server.py` immediately after the `pdf_extract_route` function (and before `if __name__ == "__main__":`):

```python
@app.route("/api/pdf/compress", methods=["POST"])
def pdf_compress_route():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400
    file = request.files["file"]
    quality = request.form.get("quality", "balanced").lower()

    target_bytes = None
    try:
        target_mb = float(request.form.get("target_mb", ""))
        if target_mb > 0:
            target_bytes = int(target_mb * 1024 * 1024)
    except (TypeError, ValueError):
        target_bytes = None

    try:
        raw = file.read()
        before_size = len(raw)
        data, engine = compress_pdf(raw, quality=quality, target_bytes=target_bytes)
        after_size = len(data)
        stem = Path(file.filename).stem if file.filename else "pdf"
        response = send_file(
            io.BytesIO(data), mimetype="application/pdf",
            as_attachment=True, download_name=f"{stem}_compressed.pdf",
        )
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["X-Compress-Engine"] = engine
        response.headers["Access-Control-Expose-Headers"] = \
            "X-Before-Size, X-After-Size, X-Compress-Engine"
        return response
    except Exception as e:
        return jsonify(error=str(e)), 500
```

- [ ] **Step 3: Verify the route**

```bash
lsof -ti tcp:5002 | xargs kill 2>/dev/null
python3 server.py > /tmp/srv.log 2>&1 &
SERVER_PID=$!
for i in $(seq 1 20); do curl -s -o /dev/null http://localhost:5002/ && break; sleep 0.5; done

# Build a ~1MB noisy test PDF
python3 -c "
import io, fitz
from PIL import Image
doc = fitz.open()
for _ in range(3):
    n = Image.effect_noise((800,800),90).convert('RGB')
    b = io.BytesIO(); n.save(b,format='JPEG',quality=95)
    p = doc.new_page(width=800,height=800); p.insert_image(p.rect, stream=b.getvalue())
open('/tmp/big.pdf','wb').write(doc.tobytes()); doc.close()
import os; print('source bytes', os.path.getsize('/tmp/big.pdf'))
"

echo -n "balanced preset: "
curl -s -D - -F "file=@/tmp/big.pdf" -F "quality=balanced" http://localhost:5002/api/pdf/compress -o /tmp/c1.pdf | grep -iE "x-(before|after)-size|x-compress-engine"
python3 -c "import os;print('  c1 bytes', os.path.getsize('/tmp/c1.pdf'))"

echo -n "target 0.2MB: "
curl -s -D - -F "file=@/tmp/big.pdf" -F "target_mb=0.2" http://localhost:5002/api/pdf/compress -o /tmp/c2.pdf | grep -iE "x-after-size|x-compress-engine"
python3 -c "import os;print('  c2 bytes', os.path.getsize('/tmp/c2.pdf'), 'under 0.2MB:', os.path.getsize('/tmp/c2.pdf') <= 0.2*1024*1024)"

kill $SERVER_PID 2>/dev/null
```

Expected: `c1` smaller than source with engine header `ghostscript` or `python`; `c2` ≤ 0.2 MB (`under 0.2MB: True`). Valid `%PDF` files (both open without error).

- [ ] **Step 4: Checkpoint**

Confirm the expected outputs. Re-run `python3 test_pdf.py` to confirm no regression.

---

### Task 5: Web UI — "Compress" mode in `index.html`

**Files:**
- Modify: `index.html` — PDF mode toggle, a compress options block, the PDF JS (mode switch, add-files, convert handler).

**Interfaces:**
- Consumes: `POST /api/pdf/compress`.
- Produces: UI only. Manual verification.

The compress flow reuses the existing single-file queue plumbing (`pdfAddFiles`, `pdfRenderItem`, `pdfSetStatus`, `pdfDownloadLink`, `fmtSize`) exactly like `pdf2img`.

- [ ] **Step 1: Add the fourth mode button**

In the PDF mode group, after the `pdf2pages` button (added previously):

```html
<button class="fmt-btn" data-mode="compress">Compress</button>
```

- [ ] **Step 2: Add the compress options block**

After the `pdfThumbs` div and before the `pdfQueue` div, add:

```html
<div class="options-row" id="pdfCompressQualityRow" style="display:none">
  <span class="option-label">Quality</span>
  <div class="fmt-group" id="pdfCompressQualityGroup">
    <button class="fmt-btn" data-q="small">Small</button>
    <button class="fmt-btn active" data-q="balanced">Balanced</button>
    <button class="fmt-btn" data-q="high">High</button>
  </div>
</div>

<div class="options-row" id="pdfCompressTargetRow" style="display:none">
  <span class="option-label">Target size</span>
  <input type="number" id="pdfTargetInput" class="pages-input" min="0" step="0.1" placeholder="optional" />
  <span class="option-label" style="margin-left:6px">MB</span>
</div>

<div id="pdfCompressHint" class="drop-hint" style="display:none; margin-top:10px"></div>
```

(`.pages-input` styling was added in the page-export work and applies here too.)

- [ ] **Step 3: Add refs + quality picker (JS)**

Near the other PDF refs/state, add:

```javascript
const pdfCompressQualityRow = document.getElementById('pdfCompressQualityRow');
const pdfCompressTargetRow  = document.getElementById('pdfCompressTargetRow');
const pdfTargetInput        = document.getElementById('pdfTargetInput');
const pdfCompressHint       = document.getElementById('pdfCompressHint');

let pdfQuality = 'balanced';
makeOptionPicker(document.getElementById('pdfCompressQualityGroup'), btn => { pdfQuality = btn.dataset.q; });
```

- [ ] **Step 4: Wire the mode switch**

In the `makeOptionPicker(document.getElementById('pdfModeGroup'), …)` handler, add a compress branch. Replace the handler body's flag lines and display toggles with:

```javascript
  pdfMode = btn.dataset.mode;
  const img      = pdfMode === 'img2pdf';
  const toImg    = pdfMode === 'pdf2img';
  const toPages  = pdfMode === 'pdf2pages';
  const toComp   = pdfMode === 'compress';
  pdfImgOpts.style.display            = img ? '' : 'none';
  pdfFmtRow.style.display             = toImg ? '' : 'none';
  pdfDpiRow.style.display             = toImg ? '' : 'none';
  pdfPagesRow.style.display           = toPages ? '' : 'none';
  pdfPagesOutRow.style.display        = toPages ? '' : 'none';
  pdfThumbs.style.display             = toPages ? '' : 'none';
  pdfCompressQualityRow.style.display = toComp ? '' : 'none';
  pdfCompressTargetRow.style.display  = toComp ? '' : 'none';
  pdfCompressHint.style.display       = 'none';
  pdfFileList.style.display           = toPages ? 'none' : '';
  pdfQueueTitle.textContent           = toPages ? 'Export' : 'Files';
  pdfConvertBtn.textContent           = toPages ? 'Export' : toComp ? 'Compress' : 'Convert';
  pdfFileInput.accept   = img ? 'image/*,.heic,.heif' : 'application/pdf,.pdf';
  pdfFileInput.multiple = img;
  pdfDropLabel.textContent = img ? 'Drop images here or click to browse' : 'Drop a PDF here or click to browse';
  pdfDropHint.textContent  = img ? 'Combine images into a PDF'
                            : toImg ? 'Each page becomes an image'
                            : toPages ? 'Select pages to export into a new PDF'
                            : 'Shrink the PDF (Ghostscript or built-in)';
  pdfClearAll();
```

Also extend `pdfClearAll()` to hide the hint:

```javascript
  pdfCompressHint.style.display = 'none';
  pdfCompressHint.textContent = '';
```

- [ ] **Step 5: Accept one PDF in compress mode**

In `pdfAddFiles(fs)`, the existing `pdf2img` branch keeps only the last file. Make compress behave the same — change that line to:

```javascript
  if (pdfMode === 'pdf2img' || pdfMode === 'compress') { pdfClearAll(); fs = fs.slice(-1); }  // one PDF at a time
```

- [ ] **Step 6: Add the compress handler**

Add this function near `pdfConvertOne`:

```javascript
async function pdfCompressOne(item) {
  pdfSetStatus(item.id, 'working', 'Compressing…');
  pdfCompressHint.style.display = 'none';
  const fd = new FormData();
  fd.append('file', item.file);
  fd.append('quality', pdfQuality);
  const tgt = pdfTargetInput.value.trim();
  if (tgt) fd.append('target_mb', tgt);
  try {
    const res = await fetch('/api/pdf/compress', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      pdfSetStatus(item.id, 'error', err.error || 'Failed');
      return;
    }
    const blob = await res.blob();
    const before = +res.headers.get('X-Before-Size') || item.file.size;
    const after  = +res.headers.get('X-After-Size')  || blob.size;
    const engine = res.headers.get('X-Compress-Engine') || '';
    const pct = before > 0 ? Math.round((1 - after / before) * 100) : 0;
    const meta = document.getElementById(`pdf-meta-${item.id}`);
    const engineLabel = engine === 'ghostscript' ? 'Ghostscript' : engine === 'python' ? 'built-in' : '';
    if (meta) meta.textContent = `${fmtSize(before)} → ${fmtSize(after)} (${pct}% smaller)` + (engineLabel ? ` · ${engineLabel}` : '');
    item.done = true;
    const stem = item.file.name.replace(/\.[^.]+$/, '');
    pdfDownloadLink(item.id, blob, `${stem}_compressed.pdf`);
    const targetMb = parseFloat(tgt);
    if (engine === 'python' && targetMb > 0 && after > targetMb * 1024 * 1024) {
      pdfCompressHint.textContent = 'Couldn’t reach the target with the built-in compressor. Install Ghostscript (brew install ghostscript) for better, text-preserving compression.';
      pdfCompressHint.style.display = '';
    }
  } catch {
    pdfSetStatus(item.id, 'error', 'Failed');
  }
}
```

- [ ] **Step 7: Route the convert button to compress**

In the `pdfConvertBtn` click handler, after the existing `pdf2pages` early-return branch, add a compress branch before the `img2pdf`/`pdf2img` logic:

```javascript
  if (pdfMode === 'compress') {
    const pending = pdfFiles.filter(f => !f.done);
    if (!pending.length) return;
    pdfConvertBtn.disabled = true;
    for (const item of pending) await pdfCompressOne(item);
    pdfConvertBtn.disabled = false;
    return;
  }
```

- [ ] **Step 8: Syntax-check the JS**

Extract and check the script blocks (the scratchpad dir avoids deletion-blocked temp cleanup):

```bash
SP="/private/tmp/claude-501/-Users-bryglen-Work-personal-tools/692e5c0b-17ff-447c-a7ca-7d70a01af5af/scratchpad"
python3 - "$SP" <<'PY'
import re, sys, os
sp = sys.argv[1]
html = open('index.html').read()
for i, s in enumerate(re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.S)):
    open(os.path.join(sp, f"ck_{i}.js"), "w").write(s)
print("written")
PY
for f in "$SP"/ck_*.js; do node --check "$f" && echo "$(basename "$f") ok" || echo "$(basename "$f") FAIL"; done
```

Expected: each block prints `ok`.

- [ ] **Step 9: Manual browser verification**

```bash
lsof -ti tcp:5002 | xargs kill 2>/dev/null
python3 server.py > /tmp/srv.log 2>&1 &
echo "Open http://localhost:5002 → PDF tab → 'Compress'"
```

Verify by hand:
1. Drop a multi-MB PDF → file appears, button reads **Compress**.
2. Pick **Balanced**, click Compress → downloads `<name>_compressed.pdf`; the row shows `X MB → Y MB (Z% smaller) · <engine>`.
3. Type a small target (e.g. `1`) MB, Compress again → result is at/under target (or, with the built-in engine, a hint to install Ghostscript appears).
4. Switching to another PDF mode and back to Compress resets cleanly.

Then `kill` the server (port 5002).

- [ ] **Step 10: Checkpoint**

Confirm steps 8-9. Re-run `python3 test_pdf.py` (logic unaffected).

---

### Task 6: CLI parity + README

**Files:**
- Modify: `pdf_convert/pdf_converter.py` — add `_compress_cli` helper and a `4` branch in `main()`.
- Modify: `README.md` — document the Compress mode + CLI direction `4`.

**Interfaces:**
- Consumes: `compress_pdf`. No automated test (interactive I/O); manual verification.

- [ ] **Step 1: Add the CLI helper**

Add to `pdf_convert/pdf_converter.py` after `_extract_pages_cli`:

```python
def _compress_cli(source, quality, target_mb):
    data = source.read_bytes()
    target_bytes = int(target_mb * 1024 * 1024) if target_mb and target_mb > 0 else None
    out_data, engine = compress_pdf(data, quality=quality, target_bytes=target_bytes)
    out = source.with_name(f"{source.stem}_compressed.pdf")
    out.write_bytes(out_data)
    before, after = len(data), len(out_data)
    pct = round((1 - after / before) * 100) if before else 0
    print(f"✔ {source.name} → {out.name}  "
          f"{before // 1024} KB → {after // 1024} KB ({pct}% smaller) · {engine}")
```

- [ ] **Step 2: Add the `4` branch in `main()`**

Change the direction prompt to include compress, and add the branch before the final `else:`:

```python
    raw = input("Direction (1 = images→PDF, 2 = PDF→images, 3 = extract pages, 4 = compress): ").strip()
```

```python
    elif raw == "4":
        src = Path(input("PDF file path: ").strip().strip('"').strip("'")).expanduser()
        if not src.exists():
            print("Path not found."); return
        quality = ask_choice("Quality", ["small", "balanced", "high"], "balanced")
        tgt_raw = input("Target size MB (blank = none): ").strip()
        try:
            target_mb = float(tgt_raw) if tgt_raw else None
        except ValueError:
            target_mb = None
        _compress_cli(src, quality, target_mb)
```

- [ ] **Step 3: Manual verification**

```bash
python3 -c "
import io, fitz
from PIL import Image
doc = fitz.open()
for _ in range(3):
    n = Image.effect_noise((800,800),90).convert('RGB')
    b = io.BytesIO(); n.save(b,format='JPEG',quality=95)
    p = doc.new_page(width=800,height=800); p.insert_image(p.rect, stream=b.getvalue())
open('/tmp/cli_big.pdf','wb').write(doc.tobytes()); doc.close()
"
printf '4\n/tmp/cli_big.pdf\nbalanced\n0.2\n' | python3 pdf_convert/pdf_converter.py
python3 -c "import os;print('compressed bytes', os.path.getsize('/tmp/cli_big_compressed.pdf'))"
```

Expected: prints a `✔ … KB → … KB (…% smaller) · <engine>` line; the compressed file is smaller than the source.

- [ ] **Step 4: Checkpoint + README**

Run `python3 test_pdf.py` one final time — all `ok`, 0 failures.

Update `README.md`:
- In the **PDF Converter** section, add a `**Compress PDF:**` bullet describing presets (Small/Balanced/High), the optional target size, and the Ghostscript-preferred / built-in-fallback behavior (note the fallback rasterizes; suggest `brew install ghostscript`).
- In the **CLI Tools** PDF line, mention direction `4 = compress`.
- (Optional) note Ghostscript as an optional dependency under Requirements.

---

## Self-Review

**Spec coverage:**
- Fourth "Compress" mode → Task 5. ✓
- Quality presets (Small/Balanced/High, default Balanced) → constants Task 1; UI Task 5; CLI Task 6. ✓
- Optional target size with ladder → `compress_pdf` Task 3; route parse Task 4; UI input Task 5. ✓
- Ghostscript primary + Python fallback (on absence or error) → Tasks 1-3 (`gs_available`, both runners, orchestrator try/except). ✓
- Engine reported accurately (incl. after fallback) → `compress_pdf` returns `(data, engine)` Task 3; `X-Compress-Engine` header Task 4; UI label + hint Task 5. ✓
- Original returned unchanged when already under target → Task 3 + test. ✓
- Route stateless with size headers → Task 4. ✓
- Python fallback rasterizes (documented tradeoff) → docstring Task 1; README Task 6; UI hint Task 5. ✓
- Testing (gs bool, python shrink+pagecount, target met/identity, presets, gs path skip) → Tasks 1-3. ✓
- CLI parity → Task 6. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; verification steps give exact commands and expected output. ✓

**Type consistency:** `gs_available() -> bool`; both runners `(_compress_with_ghostscript|_compress_with_python)(bytes, dpi:int, jpeg_quality:int) -> bytes`; `compress_pdf(bytes, quality:str, target_bytes:int|None) -> (bytes, str)` used consistently in Task 4 route and Task 6 CLI. Form fields `quality`/`target_mb` and headers `X-Before-Size`/`X-After-Size`/`X-Compress-Engine` match between Task 4 (server) and Task 5 (client). UI symbols (`pdfQuality`, `pdfTargetInput`, `pdfCompressHint`, `pdfCompressOne`) defined before use. ✓
