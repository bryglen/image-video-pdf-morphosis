# PDF Page Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "PDF → Pages" mode that exports selected pages of a PDF into a new combined PDF or one PDF per page.

**Architecture:** PDF logic lives in `pdf_convert/pdf_converter.py` (pure functions, unit-tested in `test_pdf.py`, shared with the CLI). `server.py` adds two thin, stateless Flask routes that call those functions. `index.html` gains a third PDF mode with a thumbnail picker + page-range box that stay in sync, and a combined/per-page output toggle.

**Tech Stack:** Python 3.9+, Flask, PyMuPDF (`fitz`), Pillow; vanilla HTML/CSS/JS (no external JS libraries).

## Global Constraints

- **No new dependencies.** Use only what `pyproject.toml` already lists (pillow, pillow-heif, flask, pymupdf).
- **Server is stateless.** No server-side caching of uploads; the browser holds the `File` and re-sends bytes on each request.
- **`index.html` stays self-contained.** No CDN scripts, no external JS libraries.
- **Lossless extraction.** Copy pages with PyMuPDF `insert_pdf` — never rasterize.
- **Page numbers are 1-based** everywhere in interfaces and filenames.
- **Test style:** plain functions named `test_*` with bare `assert`s in `test_pdf.py`; no pytest. The `__main__` block auto-discovers and runs them. Output filenames from functions are generic (`extracted.pdf`, `page_001.pdf`); the server route prepends the source stem.
- **This directory is NOT a git repository.** There is nothing to commit to. The end-of-task checkpoint is **running the full test suite** (`python3 test_pdf.py`), not a git commit.
- **Environment for all commands:** run from the repo root `/Users/bryglen/Work/personal/tools` with the venv active:
  ```bash
  cd /Users/bryglen/Work/personal/tools
  source image_convert/.venv/bin/activate
  ```

---

### Task 1: `parse_page_ranges` — page-range string parser

**Files:**
- Modify: `pdf_convert/pdf_converter.py` (add function near the other logic functions, after `pdf_to_images`)
- Test: `test_pdf.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `parse_page_ranges(text: str, page_count: int) -> list[int]` — returns a sorted, de-duplicated list of 1-based page numbers. Raises `ValueError` on empty input, unparseable tokens, or pages outside `1..page_count`.

- [ ] **Step 1: Write the failing tests**

Add to `test_pdf.py` (add `parse_page_ranges` to the import line at the top — change line 7 to
`from pdf_convert.pdf_converter import images_to_pdf, pdf_to_images, parse_page_ranges`):

```python
def test_parse_page_ranges_single():
    assert parse_page_ranges("3", 10) == [3]


def test_parse_page_ranges_list_and_range():
    assert parse_page_ranges("1,3,5-7", 10) == [1, 3, 5, 6, 7]


def test_parse_page_ranges_dedupe_and_order():
    assert parse_page_ranges("5,1,5,2-3", 10) == [1, 2, 3, 5]


def test_parse_page_ranges_whitespace_tolerant():
    assert parse_page_ranges(" 1 , 4 - 6 ", 10) == [1, 4, 5, 6]


def test_parse_page_ranges_reversed_range():
    assert parse_page_ranges("7-5", 10) == [5, 6, 7]


def test_parse_page_ranges_out_of_range_raises():
    try:
        parse_page_ranges("1,99", 10)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_page_ranges_zero_raises():
    try:
        parse_page_ranges("0", 10)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_page_ranges_empty_raises():
    try:
        parse_page_ranges("   ", 10)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_page_ranges_garbage_raises():
    try:
        parse_page_ranges("1,abc", 10)
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_pdf.py`
Expected: FAIL — `ImportError: cannot import name 'parse_page_ranges'` (the top-level import in `test_pdf.py` can't resolve yet).

- [ ] **Step 3: Write the implementation**

Add to `pdf_convert/pdf_converter.py` after `pdf_to_images`:

```python
def parse_page_ranges(text, page_count):
    """Parse '1,3,5-7' into a sorted, de-duplicated list of 1-based page numbers.

    Accepts single numbers, comma-separated lists, and inclusive 'a-b' ranges
    (reversed ranges are normalized). Raises ValueError on empty input,
    unparseable tokens, or pages outside 1..page_count.
    """
    tokens = [t.strip() for t in str(text or "").split(",")]
    tokens = [t for t in tokens if t]
    if not tokens:
        raise ValueError("No pages specified")

    pages = set()
    for tok in tokens:
        if "-" in tok:
            lo_s, _, hi_s = tok.partition("-")
            lo_s, hi_s = lo_s.strip(), hi_s.strip()
            if not (lo_s.isdigit() and hi_s.isdigit()):
                raise ValueError(f"Invalid range: {tok!r}")
            lo, hi = int(lo_s), int(hi_s)
            if lo > hi:
                lo, hi = hi, lo
            pages.update(range(lo, hi + 1))
        else:
            if not tok.isdigit():
                raise ValueError(f"Invalid page: {tok!r}")
            pages.add(int(tok))

    ordered = sorted(pages)
    for p in ordered:
        if p < 1 or p > page_count:
            raise ValueError(f"Page {p} out of range (1-{page_count})")
    return ordered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_pdf.py`
Expected: PASS — all `test_parse_page_ranges_*` print `ok` and the suite reports all passed.

- [ ] **Step 5: Checkpoint (no VCS — run full suite)**

Run: `python3 test_pdf.py`
Expected: every test prints `ok ...` and the final line reports the new total with 0 failures.

---

### Task 2: `pdf_page_count` + `pdf_thumbnails` — page count and thumbnail rendering

**Files:**
- Modify: `pdf_convert/pdf_converter.py` (add both functions after `parse_page_ranges`)
- Test: `test_pdf.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `pdf_page_count(pdf_bytes: bytes) -> int` — number of pages in the PDF.
  - `pdf_thumbnails(pdf_bytes: bytes, dpi: int = 40) -> list[tuple[int, bytes]]` — `[(page_number, png_bytes), ...]`, 1-based, one entry per page.

- [ ] **Step 1: Write the failing tests**

Add `pdf_page_count, pdf_thumbnails` to the import line in `test_pdf.py`, then add:

```python
def test_pdf_page_count():
    pdf = images_to_pdf([_img(80, 80, (1, 2, 3)), _img(80, 80, (4, 5, 6)),
                         _img(80, 80, (7, 8, 9))])
    assert pdf_page_count(pdf) == 3


def test_pdf_thumbnails_one_per_page():
    pdf = images_to_pdf([_img(200, 100, (10, 20, 30)), _img(100, 200, (40, 50, 60))])
    thumbs = pdf_thumbnails(pdf)
    assert [n for n, _ in thumbs] == [1, 2]
    assert Image.open(io.BytesIO(thumbs[0][1])).format == "PNG"


def test_pdf_thumbnails_are_small():
    pdf = images_to_pdf([_img(2000, 1000, (10, 20, 30))])
    thumb = Image.open(io.BytesIO(pdf_thumbnails(pdf, dpi=40)[0][1]))
    full = Image.open(io.BytesIO(pdf_to_images(pdf, dpi=150)[0][1]))
    assert thumb.width < full.width
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_pdf.py`
Expected: FAIL — `ImportError: cannot import name 'pdf_page_count'`.

- [ ] **Step 3: Write the implementation**

Add to `pdf_convert/pdf_converter.py` after `parse_page_ranges`:

```python
def pdf_page_count(pdf_bytes):
    """Return the number of pages in the PDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return doc.page_count
    finally:
        doc.close()


def pdf_thumbnails(pdf_bytes, dpi=40):
    """Render each page to a small PNG. Return [(page_number, png_bytes), ...] 1-based."""
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    results = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix)
            results.append((i, pix.tobytes("png")))
    finally:
        doc.close()
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_pdf.py`
Expected: PASS — the three new tests print `ok`.

- [ ] **Step 5: Checkpoint (run full suite)**

Run: `python3 test_pdf.py`
Expected: all tests `ok`, 0 failures.

---

### Task 3: `extract_pdf_pages` — lossless page extraction

**Files:**
- Modify: `pdf_convert/pdf_converter.py` (add function after `pdf_thumbnails`)
- Test: `test_pdf.py`

**Interfaces:**
- Consumes: nothing (callers pass an explicit page list, produced by `parse_page_ranges` at the route layer).
- Produces: `extract_pdf_pages(pdf_bytes: bytes, pages: list[int], combine: bool = True) -> list[tuple[str, bytes]]`
  - `combine=True`  → `[("extracted.pdf", bytes)]` (one PDF, pages ascending).
  - `combine=False` → `[("page_001.pdf", bytes), ("page_003.pdf", bytes), ...]` (one per page; filename uses the source page number, 1-based, zero-padded to 3).
  - Raises `ValueError` if `pages` is empty or contains a page outside `1..page_count`.

- [ ] **Step 1: Write the failing tests**

Add `extract_pdf_pages` to the import line in `test_pdf.py`, then add:

```python
def test_extract_combined_page_count():
    pdf = images_to_pdf([_img(80, 80, (i, i, i)) for i in (1, 2, 3, 4, 5)])
    out = extract_pdf_pages(pdf, [1, 3, 5], combine=True)
    assert len(out) == 1
    assert out[0][0] == "extracted.pdf"
    doc = fitz.open(stream=out[0][1], filetype="pdf")
    assert doc.page_count == 3
    doc.close()


def test_extract_per_page_filenames():
    pdf = images_to_pdf([_img(80, 80, (i, i, i)) for i in (1, 2, 3, 4, 5)])
    out = extract_pdf_pages(pdf, [1, 3, 5], combine=False)
    assert [n for n, _ in out] == ["page_001.pdf", "page_003.pdf", "page_005.pdf"]
    for _, data in out:
        doc = fitz.open(stream=data, filetype="pdf")
        assert doc.page_count == 1
        doc.close()


def test_extract_preserves_text_not_rasterized():
    # Build a PDF with real text, extract it, confirm the text survives (lossless).
    src = fitz.open()
    page = src.new_page()
    page.insert_text((72, 72), "Hello PDF")
    page2 = src.new_page()
    page2.insert_text((72, 72), "Second page")
    pdf_bytes = src.tobytes()
    src.close()

    out = extract_pdf_pages(pdf_bytes, [1], combine=True)
    doc = fitz.open(stream=out[0][1], filetype="pdf")
    assert "Hello PDF" in doc[0].get_text()
    doc.close()


def test_extract_empty_raises():
    pdf = images_to_pdf([_img(80, 80, (1, 2, 3))])
    try:
        extract_pdf_pages(pdf, [], combine=True)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_extract_out_of_range_raises():
    pdf = images_to_pdf([_img(80, 80, (1, 2, 3))])
    try:
        extract_pdf_pages(pdf, [1, 9], combine=True)
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_pdf.py`
Expected: FAIL — `ImportError: cannot import name 'extract_pdf_pages'`.

- [ ] **Step 3: Write the implementation**

Add to `pdf_convert/pdf_converter.py` after `pdf_thumbnails`:

```python
def extract_pdf_pages(pdf_bytes, pages, combine=True):
    """Copy the given 1-based pages into new PDF(s), preserving text/vectors.

    combine=True  -> [("extracted.pdf", bytes)]            (one PDF, pages ascending)
    combine=False -> [("page_001.pdf", bytes), ...]        (one PDF per page)
    Raises ValueError on empty selection or out-of-range page numbers.
    """
    if not pages:
        raise ValueError("No pages provided")

    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        ordered = sorted(set(pages))
        for p in ordered:
            if p < 1 or p > src.page_count:
                raise ValueError(f"Page {p} out of range (1-{src.page_count})")

        results = []
        if combine:
            out = fitz.open()
            try:
                for p in ordered:
                    out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
                results.append(("extracted.pdf", out.tobytes()))
            finally:
                out.close()
        else:
            for p in ordered:
                out = fitz.open()
                try:
                    out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
                    results.append((f"page_{p:03d}.pdf", out.tobytes()))
                finally:
                    out.close()
        return results
    finally:
        src.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_pdf.py`
Expected: PASS — all five new tests print `ok`.

- [ ] **Step 5: Checkpoint (run full suite)**

Run: `python3 test_pdf.py`
Expected: all tests `ok`, 0 failures. This completes the logic layer.

---

### Task 4: Flask routes — `/api/pdf/thumbnails` and `/api/pdf/extract`

**Files:**
- Modify: `server.py` (import line 8; add `base64` to line 1; add two routes after the `pdf_to_images_route` function, before `if __name__ == "__main__":`)

**Interfaces:**
- Consumes: `parse_page_ranges`, `pdf_page_count`, `pdf_thumbnails`, `extract_pdf_pages` from `pdf_convert.pdf_converter`.
- Produces (HTTP):
  - `POST /api/pdf/thumbnails` (multipart `file`) → JSON `{ "page_count": int, "thumbnails": [ {"page": int, "dataUrl": "data:image/png;base64,…"}, … ] }`.
  - `POST /api/pdf/extract` (multipart `file`, form `pages` string, form `combine` `"true"`/`"false"`) → a `.pdf` (single result) or `.zip` (multiple), with `X-Before-Size`/`X-After-Size` headers.

- [ ] **Step 1: Update imports**

In `server.py` line 1, add `base64`:

```python
import io, sys, re, uuid, shutil, threading, subprocess, tempfile, zipfile, base64
```

In `server.py` line 8, extend the PDF import:

```python
from pdf_convert.pdf_converter import (
    images_to_pdf, pdf_to_images,
    parse_page_ranges, pdf_page_count, pdf_thumbnails, extract_pdf_pages,
)
```

- [ ] **Step 2: Add the two routes**

Insert into `server.py` immediately after the `pdf_to_images_route` function (and before `if __name__ == "__main__":`):

```python
@app.route("/api/pdf/thumbnails", methods=["POST"])
def pdf_thumbnails_route():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400
    file = request.files["file"]
    try:
        raw = file.read()
        thumbs = pdf_thumbnails(raw)
        if not thumbs:
            return jsonify(error="PDF has no pages"), 500
        return jsonify(
            page_count=len(thumbs),
            thumbnails=[
                {"page": n,
                 "dataUrl": "data:image/png;base64," + base64.b64encode(b).decode("ascii")}
                for n, b in thumbs
            ],
        )
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/pdf/extract", methods=["POST"])
def pdf_extract_route():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400
    file = request.files["file"]
    pages_text = request.form.get("pages", "")
    combine = request.form.get("combine", "true").lower() != "false"

    try:
        raw = file.read()
        before_size = len(raw)
        pages = parse_page_ranges(pages_text, pdf_page_count(raw))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=str(e)), 500

    try:
        results = extract_pdf_pages(raw, pages, combine=combine)
        stem = Path(file.filename).stem if file.filename else "pdf"

        if len(results) == 1:
            name, data = results[0]
            payload, after_size = io.BytesIO(data), len(data)
            mime = "application/pdf"
            download_name = f"{stem}_{name}"
        else:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in results:
                    zf.writestr(name, data)
            after_size = payload.tell()
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

- [ ] **Step 3: Manually verify the routes**

Start the server and exercise both routes with a generated test PDF:

```bash
python3 server.py &
SERVER_PID=$!
sleep 2

# Make a 5-page test PDF
python3 -c "
from PIL import Image
from pdf_convert.pdf_converter import images_to_pdf
open('/tmp/t.pdf','wb').write(images_to_pdf([Image.new('RGB',(200,200),(i*40,i*40,i*40)) for i in range(1,6)]))
"

# thumbnails: expect page_count 5
curl -s -F "file=@/tmp/t.pdf" http://localhost:5002/api/pdf/thumbnails | python3 -c "import sys,json; d=json.load(sys.stdin); print('page_count', d['page_count'], 'thumbs', len(d['thumbnails']))"

# combined extract of pages 1,3,5 -> a PDF
curl -s -F "file=@/tmp/t.pdf" -F "pages=1,3,5" -F "combine=true" http://localhost:5002/api/pdf/extract -o /tmp/out.pdf
python3 -c "import fitz; d=fitz.open('/tmp/out.pdf'); print('combined pages', d.page_count); d.close()"

# per-page extract of pages 1,3,5 -> a ZIP
curl -s -F "file=@/tmp/t.pdf" -F "pages=1,3,5" -F "combine=false" http://localhost:5002/api/pdf/extract -o /tmp/out.zip
python3 -c "import zipfile; z=zipfile.ZipFile('/tmp/out.zip'); print('zip names', z.namelist())"

# out-of-range -> 400 JSON error
curl -s -o /dev/null -w "%{http_code}\n" -F "file=@/tmp/t.pdf" -F "pages=1,99" http://localhost:5002/api/pdf/extract

kill $SERVER_PID
```

Expected output:
- `page_count 5 thumbs 5`
- `combined pages 3`
- `zip names ['page_001.pdf', 'page_003.pdf', 'page_005.pdf']`
- `400`

- [ ] **Step 4: Checkpoint**

Confirm all four expected outputs above match. The logic-layer suite is unaffected; optionally re-run `python3 test_pdf.py` to confirm nothing regressed.

---

### Task 5: Web UI — "PDF → Pages" mode in `index.html`

**Files:**
- Modify: `index.html` — the PDF tab markup (around lines 374-422) and the PDF converter JS (around lines 715-770+).

**Interfaces:**
- Consumes: `POST /api/pdf/thumbnails` and `POST /api/pdf/extract` from Task 4.
- Produces: no code interface (UI only). Manual browser verification.

Reference the existing PDF mode toggle and option-picker patterns already in the file (`pdfModeGroup`, `makeOptionPicker`, `pdfMode` switching) and match their style.

- [ ] **Step 1: Add the third mode button**

In the PDF mode group (currently the two buttons at `index.html:379-380`), add a third button:

```html
<button class="fmt-btn" data-mode="pdf2pages">PDF &#8594; Pages</button>
```

So the group reads: `Images → PDF`, `PDF → Images`, `PDF → Pages`.

- [ ] **Step 2: Add the Pages mode UI block**

After the existing `pdfDpiRow` options row (`index.html:407-414`) and before the `pdfQueue` div, add a container shown only in `pdf2pages` mode:

```html
<div class="options-row" id="pdfPagesRow" style="display:none">
  <span class="opt-label">Pages</span>
  <input type="text" id="pdfPagesInput" class="pages-input" placeholder="e.g. 1,3,5-7" />
</div>
<div class="options-row" id="pdfPagesOutRow" style="display:none">
  <span class="opt-label">Output</span>
  <div class="fmt-group" id="pdfPagesOutGroup">
    <button class="fmt-btn active" data-combine="true">One combined PDF</button>
    <button class="fmt-btn" data-combine="false">One PDF per page</button>
  </div>
</div>
<div id="pdfThumbs" class="pdf-thumbs" style="display:none"></div>
```

Add styling in the `<style>` block (match existing token/color variables already used in the file — reuse `var(--accent)` / border styles consistent with `.fmt-btn`):

```css
.pages-input { padding:6px 10px; border-radius:8px; border:1px solid var(--border);
  background:var(--input-bg, transparent); color:inherit; width:180px; font-size:14px; }
.pdf-thumbs { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }
.pdf-thumb { position:relative; border:2px solid transparent; border-radius:6px;
  cursor:pointer; padding:0; background:none; line-height:0; }
.pdf-thumb img { width:90px; height:auto; display:block; border-radius:4px;
  box-shadow:0 1px 4px rgba(0,0,0,.25); opacity:.45; transition:opacity .12s; }
.pdf-thumb.selected { border-color:var(--accent); }
.pdf-thumb.selected img { opacity:1; }
.pdf-thumb .pg-num { position:absolute; bottom:4px; right:6px; font-size:11px;
  background:rgba(0,0,0,.6); color:#fff; padding:1px 5px; border-radius:8px; }
```

- [ ] **Step 3: Wire mode switching**

Extend the existing `makeOptionPicker(document.getElementById('pdfModeGroup'), …)` handler (`index.html:734-744`) so it also toggles the new rows and resets selection. Replace the handler body with:

```javascript
makeOptionPicker(document.getElementById('pdfModeGroup'), btn => {
  pdfMode = btn.dataset.mode;
  const img    = pdfMode === 'img2pdf';
  const toImg  = pdfMode === 'pdf2img';
  const toPages = pdfMode === 'pdf2pages';
  pdfImgOpts.style.display    = img ? '' : 'none';
  pdfFmtRow.style.display     = toImg ? '' : 'none';
  pdfDpiRow.style.display     = toImg ? '' : 'none';
  pdfPagesRow.style.display    = toPages ? '' : 'none';
  pdfPagesOutRow.style.display = toPages ? '' : 'none';
  pdfThumbs.style.display      = toPages ? '' : 'none';
  pdfFileInput.accept = img ? 'image/*,.heic,.heif' : 'application/pdf,.pdf';
  pdfFileInput.multiple = img;
  pdfDropLabel.textContent = img ? 'Drop images here or click to browse' : 'Drop a PDF here or click to browse';
  pdfDropHint.textContent  = img ? 'Combine images into a PDF'
                            : toImg ? 'Each page becomes an image'
                            : 'Select pages to export into a new PDF';
  pdfClearAll();
});
```

Add the new element refs and state near the existing PDF refs/state (`index.html:716-729`):

```javascript
const pdfPagesRow    = document.getElementById('pdfPagesRow');
const pdfPagesOutRow = document.getElementById('pdfPagesOutRow');
const pdfPagesInput  = document.getElementById('pdfPagesInput');
const pdfThumbs      = document.getElementById('pdfThumbs');

let pdfPageCount = 0;
let pdfSelected = new Set();   // 1-based selected page numbers
let pdfCombine = true;
let pdfPagesFile = null;       // the dropped PDF File for pdf2pages

makeOptionPicker(document.getElementById('pdfPagesOutGroup'), btn => {
  pdfCombine = btn.dataset.combine === 'true';
});
```

- [ ] **Step 4: Add the JS parser mirror + sync helpers**

Add these functions in the PDF JS section. `parsePageRanges` mirrors the Python `parse_page_ranges` (returns `[]` on any invalid/empty input rather than throwing, since this drives live UI highlighting):

```javascript
function parsePageRanges(text, pageCount) {
  const out = new Set();
  const toks = String(text || '').split(',').map(s => s.trim()).filter(Boolean);
  for (const tok of toks) {
    if (tok.includes('-')) {
      const [a, b] = tok.split('-').map(s => s.trim());
      if (!/^\d+$/.test(a) || !/^\d+$/.test(b)) return [];
      let lo = +a, hi = +b; if (lo > hi) [lo, hi] = [hi, lo];
      for (let p = lo; p <= hi; p++) out.add(p);
    } else {
      if (!/^\d+$/.test(tok)) return [];
      out.add(+tok);
    }
  }
  const arr = [...out].sort((x, y) => x - y);
  return arr.every(p => p >= 1 && p <= pageCount) ? arr : [];
}

function pagesToText(set) {
  // Collapse a sorted page set into compact ranges: {1,2,3,5} -> "1-3,5"
  const arr = [...set].sort((x, y) => x - y);
  const parts = [];
  let i = 0;
  while (i < arr.length) {
    let j = i;
    while (j + 1 < arr.length && arr[j + 1] === arr[j] + 1) j++;
    parts.push(i === j ? `${arr[i]}` : `${arr[i]}-${arr[j]}`);
    i = j + 1;
  }
  return parts.join(',');
}

function renderThumbSelection() {
  [...pdfThumbs.children].forEach(el => {
    const pg = +el.dataset.page;
    el.classList.toggle('selected', pdfSelected.has(pg));
  });
  pdfConvertBtn.disabled = pdfSelected.size === 0;
}

function syncTextFromSelection() {
  pdfPagesInput.value = pagesToText(pdfSelected);
  renderThumbSelection();
}
```

- [ ] **Step 5: Load thumbnails on drop (pdf2pages)**

Update `pdfAddFiles` so that in `pdf2pages` mode it uploads the PDF to `/api/pdf/thumbnails` and renders the picker. Add this branch at the top of `pdfAddFiles(fs)` (which is at `index.html:758`), before the existing `pdf2img` handling:

```javascript
async function pdfLoadPagesPdf(file) {
  pdfPagesFile = file;
  pdfThumbs.innerHTML = '<div class="drop-hint">Rendering pages…</div>';
  pdfThumbs.style.display = '';
  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch('/api/pdf/thumbnails', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to render');
    pdfPageCount = data.page_count;
    pdfSelected = new Set(data.thumbnails.map(t => t.page));  // all selected by default
    pdfThumbs.innerHTML = '';
    for (const t of data.thumbnails) {
      const el = document.createElement('button');
      el.className = 'pdf-thumb';
      el.dataset.page = t.page;
      el.innerHTML = `<img src="${t.dataUrl}" alt="page ${t.page}"><span class="pg-num">${t.page}</span>`;
      el.addEventListener('click', () => {
        const pg = +el.dataset.page;
        if (pdfSelected.has(pg)) pdfSelected.delete(pg); else pdfSelected.add(pg);
        syncTextFromSelection();
      });
      pdfThumbs.appendChild(el);
    }
    pdfQueue.style.display = '';
    syncTextFromSelection();
  } catch (e) {
    pdfThumbs.innerHTML = `<div class="drop-hint">Error: ${e.message}</div>`;
  }
}
```

And in `pdfAddFiles(fs)`, branch at the very top:

```javascript
function pdfAddFiles(fs) {
  if (pdfMode === 'pdf2pages') {
    const pdf = fs.find(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    if (pdf) pdfLoadPagesPdf(pdf);
    return;
  }
  if (pdfMode === 'pdf2img') { pdfClearAll(); fs = fs.slice(-1); }  // one PDF at a time
  // ... existing body unchanged ...
```

Wire the text box to update the selection (add near the other event listeners):

```javascript
pdfPagesInput.addEventListener('input', () => {
  const arr = parsePageRanges(pdfPagesInput.value, pdfPageCount);
  pdfSelected = new Set(arr);
  renderThumbSelection();
});
```

Extend `pdfClearAll()` (`index.html:751`) to also reset the new state:

```javascript
function pdfClearAll() {
  pdfFiles = [];
  pdfFileList.innerHTML = '';
  pdfQueue.style.display = 'none';
  pdfFileInput.value = '';
  pdfPagesFile = null;
  pdfPageCount = 0;
  pdfSelected = new Set();
  pdfThumbs.innerHTML = '';
  pdfPagesInput.value = '';
}
```

- [ ] **Step 6: Handle Export for pdf2pages**

In the existing `pdfConvertBtn` click handler, add a `pdf2pages` branch that posts to `/api/pdf/extract` and triggers the download. Match how the existing PDF handler reads the blob and creates an `<a download>` (reuse the same download helper/pattern already in the file). The branch:

```javascript
// inside the pdfConvertBtn click handler, before the existing img2pdf/pdf2img logic:
if (pdfMode === 'pdf2pages') {
  if (!pdfPagesFile || pdfSelected.size === 0) return;
  const fd = new FormData();
  fd.append('file', pdfPagesFile);
  fd.append('pages', pagesToText(pdfSelected));
  fd.append('combine', pdfCombine ? 'true' : 'false');
  pdfConvertBtn.disabled = true;
  try {
    const res = await fetch('/api/pdf/extract', { method: 'POST', body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || 'Export failed');
    }
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^"]+)"?/);
    const name = m ? m[1] : (pdfCombine ? 'extracted.pdf' : 'pages.zip');
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert(e.message);
  } finally {
    pdfConvertBtn.disabled = pdfSelected.size === 0;
  }
  return;
}
```

(If the existing click handler is not `async`, make it `async`, consistent with how the other fetch-based handlers in the file are written.)

- [ ] **Step 7: Manual browser verification**

```bash
python3 server.py &
SERVER_PID=$!
sleep 2
echo "Open http://localhost:5002 → PDF tab → 'PDF → Pages'"
```

Verify by hand:
1. Drop a multi-page PDF → thumbnails render, all selected, Pages box shows e.g. `1-5`.
2. Click page 2 to deselect → Pages box updates to `1,3-5`; thumbnail 2 dims.
3. Type `2,4` in the Pages box → only thumbnails 2 and 4 highlight.
4. Output = "One combined PDF", Export → downloads a single PDF with the selected pages.
5. Output = "One PDF per page" with 2+ pages, Export → downloads a `.zip` of per-page PDFs.
6. Clear the Pages box → Export button disables.

Then `kill $SERVER_PID`.

- [ ] **Step 8: Checkpoint**

Confirm all six UI checks pass. Re-run `python3 test_pdf.py` to confirm the logic layer is still green.

---

### Task 6: CLI parity — third direction in `pdf_converter.py`

**Files:**
- Modify: `pdf_convert/pdf_converter.py` — add a `_extract_pages_cli` helper and a `3` branch in `main()`.

**Interfaces:**
- Consumes: `parse_page_ranges`, `pdf_page_count`, `extract_pdf_pages` (same module).
- Produces: CLI direction `3 = extract pages`. No automated test (interactive I/O); manual verification.

- [ ] **Step 1: Add the CLI helper**

Add to `pdf_convert/pdf_converter.py` after `_pdf_to_images_cli`:

```python
def _extract_pages_cli(source, pages_text, combine):
    data = source.read_bytes()
    pages = parse_page_ranges(pages_text, pdf_page_count(data))
    results = extract_pdf_pages(data, pages, combine=combine)
    if len(results) == 1 and combine:
        out = source.with_name(f"{source.stem}_extracted.pdf")
        out.write_bytes(results[0][1])
        print(f"✔ {source.name} → {out.name} ({len(pages)} page(s))")
    else:
        out_dir = source.with_name(f"{source.stem}_pages")
        out_dir.mkdir(exist_ok=True)
        for name, b in results:
            (out_dir / name).write_bytes(b)
        print(f"✔ {source.name} → {len(results)} file(s) in {out_dir.name}/")
```

- [ ] **Step 2: Add the `3` branch in `main()`**

In `main()`, update the prompt and add the branch. Change the first `input(...)` line to:

```python
    raw = input("Direction (1 = images→PDF, 2 = PDF→images, 3 = extract pages): ").strip()
```

Add before the final `else:`:

```python
    elif raw == "3":
        src = Path(input("PDF file path: ").strip().strip('"').strip("'")).expanduser()
        if not src.exists():
            print("Path not found."); return
        pages_text = input("Pages (e.g. 1,3,5-7): ").strip()
        combine = ask_yes_no("Combine into one PDF?", default=True)
        try:
            _extract_pages_cli(src, pages_text, combine)
        except ValueError as e:
            print(f"Error: {e}")
```

- [ ] **Step 3: Manual verification**

```bash
python3 -c "
from PIL import Image
from pdf_convert.pdf_converter import images_to_pdf
open('/tmp/cli.pdf','wb').write(images_to_pdf([Image.new('RGB',(120,120),(i*30,i*30,i*30)) for i in range(1,5)]))
"
printf '3\n/tmp/cli.pdf\n1,3\ny\n' | python3 pdf_convert/pdf_converter.py
python3 -c "import fitz; d=fitz.open('/tmp/cli_extracted.pdf'); print('cli combined pages', d.page_count); d.close()"
```

Expected: prints `✔ cli.pdf → cli_extracted.pdf (2 page(s))` then `cli combined pages 2`.

- [ ] **Step 4: Checkpoint**

Run `python3 test_pdf.py` one final time — all tests `ok`, 0 failures. Update `README.md`'s PDF Converter section to mention the new "PDF → Pages" capability (extract selected pages to a combined PDF or one-per-page) and the CLI direction `3`.

---

## Self-Review

**Spec coverage:**
- Third "PDF → Pages" mode → Task 5. ✓
- Thumbnail picker + page-range box in sync → Task 5 (Steps 4-5, `parsePageRanges`/`pagesToText`). ✓
- `parse_page_ranges` as single source of truth → Task 1; JS mirror in Task 5. ✓
- `pdf_thumbnails` → Task 2. ✓
- `extract_pdf_pages` lossless (insert_pdf, not rasterized) → Task 3 (incl. text-preservation test). ✓
- Combined vs per-page toggle → Task 3 (logic), Task 4 (route), Task 5 (UI). ✓
- `/api/pdf/thumbnails` + `/api/pdf/extract` stateless routes, size headers, zip for multi → Task 4. ✓
- Error handling (empty/out-of-range/corrupt) → Task 1/Task 3 raise; Task 4 maps to 400/500; Task 5 disables Export. ✓
- Testing in `test_pdf.py` → Tasks 1-3. ✓
- CLI parity → Task 6. ✓
- No new deps / self-contained UI / stateless server → Global Constraints, honored throughout. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; manual-verification steps give exact commands and expected output. ✓

**Type consistency:** `parse_page_ranges(text, page_count) -> list[int]`, `pdf_page_count(bytes) -> int`, `pdf_thumbnails(bytes, dpi) -> list[(int, bytes)]`, `extract_pdf_pages(bytes, pages, combine) -> list[(str, bytes)]` used consistently across Tasks 1-4. Route field names (`page_count`, `thumbnails`, `page`, `dataUrl`, `pages`, `combine`) match between Task 4 (server) and Task 5 (client). Function names (`pdfLoadPagesPdf`, `parsePageRanges`, `pagesToText`, `renderThumbSelection`, `syncTextFromSelection`) are defined before use. ✓
