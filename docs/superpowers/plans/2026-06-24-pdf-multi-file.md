# PDF Multi-File (Batch) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let all PDF modes accept multiple PDFs — Compress and PDF → Images process each file independently (per-file download); PDF → Pages shows a section per PDF and exports a combined `pages.zip`.

**Architecture:** A new pure function `extract_pdf_pages_batch` in `pdf_convert/pdf_converter.py` plus a stateless route `POST /api/pdf/extract-batch` in `server.py`. `index.html` enables multi-file for Compress/PDF→Images (small) and replaces the single-PDF page picker with a per-PDF section model (larger frontend change).

**Tech Stack:** Python 3.9+, Flask, PyMuPDF, Pillow; vanilla HTML/CSS/JS (no external JS libraries).

## Global Constraints

- **Server stateless;** browser holds the `File`(s) and re-sends bytes per request.
- **No external JS libraries;** zipping is server-side.
- **`extract_pdf_pages_batch` returns flat `(name, bytes)` with names unique across the batch** (collision → suffix `_2`, `_3`, … before the extension).
- **Batch route single-vs-zip rule:** exactly one output → return that file; multiple → one `pages.zip`. (Mirrors `/api/pdf/to-images` and `/api/pdf/extract`.)
- **Image/Video tabs already accept multiple — do not touch them.**
- **No CLI changes** (out of scope).
- **Test style:** plain `test_*` functions with bare `assert`s in `test_pdf.py`; no pytest; `__main__` auto-discovers.
- **Not a git repo;** end-of-task checkpoint is `python3 test_pdf.py`, not a commit.
- **Environment:** run from repo root with venv active:
  ```bash
  cd /Users/bryglen/Work/personal/tools
  source image_convert/.venv/bin/activate
  ```

---

### Task 1: `extract_pdf_pages_batch` pure function

**Files:**
- Modify: `pdf_convert/pdf_converter.py` (add after `extract_pdf_pages`)
- Test: `test_pdf.py`

**Interfaces:**
- Consumes: `extract_pdf_pages` (existing).
- Produces: `extract_pdf_pages_batch(items, combine=True) -> list[tuple[str, bytes]]` where `items` is `list[(filename, pdf_bytes, pages)]` and the returned names are unique across the batch.

- [ ] **Step 1: Write the failing tests**

Add `extract_pdf_pages_batch` to the import block in `test_pdf.py`, then add:

```python
def test_extract_batch_combined_two_pdfs():
    a = images_to_pdf([_img(60, 60, (i, i, i)) for i in (1, 2, 3, 4)])
    b = images_to_pdf([_img(60, 60, (i, i, i)) for i in (5, 6, 7)])
    out = extract_pdf_pages_batch([("a.pdf", a, [1, 3]), ("b.pdf", b, [2])], combine=True)
    assert [n for n, _ in out] == ["a_extracted.pdf", "b_extracted.pdf"]
    counts = []
    for _, data in out:
        d = fitz.open(stream=data, filetype="pdf"); counts.append(d.page_count); d.close()
    assert counts == [2, 1]


def test_extract_batch_per_page_names():
    a = images_to_pdf([_img(60, 60, (i, i, i)) for i in (1, 2, 3, 4)])
    out = extract_pdf_pages_batch([("doc.pdf", a, [1, 3])], combine=False)
    assert [n for n, _ in out] == ["doc_page_001.pdf", "doc_page_003.pdf"]


def test_extract_batch_single_item_one_output():
    a = images_to_pdf([_img(60, 60, (1, 2, 3)), _img(60, 60, (4, 5, 6))])
    out = extract_pdf_pages_batch([("only.pdf", a, [2])], combine=True)
    assert len(out) == 1
    assert out[0][0] == "only_extracted.pdf"


def test_extract_batch_dedupes_names():
    a = images_to_pdf([_img(60, 60, (1, 2, 3)), _img(60, 60, (4, 5, 6))])
    b = images_to_pdf([_img(60, 60, (7, 8, 9)), _img(60, 60, (1, 1, 1))])
    out = extract_pdf_pages_batch([("dup.pdf", a, [1]), ("dup.pdf", b, [2])], combine=True)
    names = [n for n, _ in out]
    assert len(set(names)) == 2          # unique despite identical source stems
    assert names[0] == "dup_extracted.pdf"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 test_pdf.py`
Expected: FAIL — `ImportError: cannot import name 'extract_pdf_pages_batch'`.

- [ ] **Step 3: Write the implementation**

Add to `pdf_convert/pdf_converter.py` after `extract_pdf_pages`:

```python
def extract_pdf_pages_batch(items, combine=True):
    """Extract pages from several PDFs. items: list of (filename, pdf_bytes, pages).

    Returns a flat list of (name, bytes); names are unique across the whole batch.
    combine=True  -> one "<stem>_extracted.pdf" per source PDF.
    combine=False -> "<stem>_page_NNN.pdf" per selected page.
    """
    seen = {}

    def uniq(name):
        if name not in seen:
            seen[name] = 1
            return name
        seen[name] += 1
        stem, dot, ext = name.rpartition(".")
        return f"{stem}_{seen[name]}.{ext}" if dot else f"{name}_{seen[name]}"

    results = []
    for filename, pdf_bytes, pages in items:
        stem = Path(filename).stem if filename else "pdf"
        outs = extract_pdf_pages(pdf_bytes, pages, combine=combine)
        if combine:
            results.append((uniq(f"{stem}_extracted.pdf"), outs[0][1]))
        else:
            for n, data in outs:           # n like "page_001.pdf"
                results.append((uniq(f"{stem}_{n}"), data))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 test_pdf.py`
Expected: PASS — the four new tests print `ok`.

- [ ] **Step 5: Checkpoint**

Run: `python3 test_pdf.py`
Expected: all `ok`, 0 failures.

---

### Task 2: Route `POST /api/pdf/extract-batch`

**Files:**
- Modify: `server.py` (extend the PDF import; add route after `pdf_extract_route`)

**Interfaces:**
- Consumes: `parse_page_ranges`, `pdf_page_count`, `extract_pdf_pages_batch`.
- Produces (HTTP): `POST /api/pdf/extract-batch` — multipart `file` (repeated) + form `pages` (repeated, same order) + `combine`. Returns one PDF (single output) or `pages.zip` (multiple), with `X-Before-Size`/`X-After-Size`.

- [ ] **Step 1: Extend the import**

In `server.py`, add `extract_pdf_pages_batch` to the PDF import block:

```python
from pdf_convert.pdf_converter import (
    images_to_pdf, pdf_to_images,
    parse_page_ranges, pdf_page_count, pdf_thumbnails, extract_pdf_pages,
    extract_pdf_pages_batch,
    compress_pdf,
)
```

- [ ] **Step 2: Add the route**

Insert into `server.py` immediately after the `pdf_extract_route` function:

```python
@app.route("/api/pdf/extract-batch", methods=["POST"])
def pdf_extract_batch_route():
    files = request.files.getlist("file")
    page_specs = request.form.getlist("pages")
    if not files:
        return jsonify(error="No file provided"), 400
    if len(page_specs) != len(files):
        return jsonify(error="Mismatched files and page ranges"), 400
    combine = request.form.get("combine", "true").lower() != "false"

    items = []
    before_size = 0
    for f, spec in zip(files, page_specs):
        raw = f.read()
        before_size += len(raw)
        try:
            pages = parse_page_ranges(spec, pdf_page_count(raw))
        except ValueError as e:
            return jsonify(error=f"{f.filename or 'PDF'}: {e}"), 400
        except Exception as e:
            return jsonify(error=str(e)), 500
        items.append((f.filename or "pdf", raw, pages))

    try:
        results = extract_pdf_pages_batch(items, combine=combine)
        if not results:
            return jsonify(error="No pages selected"), 400
        if len(results) == 1:
            name, data = results[0]
            payload, after_size = io.BytesIO(data), len(data)
            mime, download_name = "application/pdf", name
        else:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in results:
                    zf.writestr(name, data)
            after_size = payload.tell()
            payload.seek(0)
            mime, download_name = "application/zip", "pages.zip"

        response = send_file(payload, mimetype=mime, as_attachment=True,
                             download_name=download_name)
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["Access-Control-Expose-Headers"] = "X-Before-Size, X-After-Size"
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

python3 -c "
from PIL import Image
from pdf_convert.pdf_converter import images_to_pdf
open('/tmp/a.pdf','wb').write(images_to_pdf([Image.new('RGB',(80,80),(i*40,i*40,i*40)) for i in range(1,6)]))
open('/tmp/b.pdf','wb').write(images_to_pdf([Image.new('RGB',(80,80),(i*30,i*30,i*30)) for i in range(1,4)]))
"

echo "--- two PDFs combined -> zip ---"
curl -s -D - -F "file=@/tmp/a.pdf" -F "pages=1,3" -F "file=@/tmp/b.pdf" -F "pages=2" -F "combine=true" \
  http://localhost:5002/api/pdf/extract-batch -o /tmp/out.zip | grep -iE "content-disposition|x-(before|after)-size"
python3 -c "import zipfile; z=zipfile.ZipFile('/tmp/out.zip'); print('  names', z.namelist())"

echo "--- one PDF combined -> single pdf ---"
curl -s -D - -F "file=@/tmp/a.pdf" -F "pages=2,4" -F "combine=true" \
  http://localhost:5002/api/pdf/extract-batch -o /tmp/single.pdf | grep -i content-disposition
python3 -c "import fitz; d=fitz.open('/tmp/single.pdf'); print('  pages', d.page_count); d.close()"

echo -n "--- bad range -> 400: "
curl -s -o /dev/null -w "%{http_code}\n" -F "file=@/tmp/a.pdf" -F "pages=9" http://localhost:5002/api/pdf/extract-batch

kill $SERVER_PID 2>/dev/null
```

Expected:
- two PDFs → `pages.zip` with names `['a_extracted.pdf', 'b_extracted.pdf']`.
- one PDF combined → `single.pdf` named `a_extracted.pdf`, `pages 2`.
- bad range → `400`.

- [ ] **Step 4: Checkpoint**

Confirm the outputs; re-run `python3 test_pdf.py` to confirm no regression.

---

### Task 3: Multi-file for Compress and PDF → Images (frontend)

**Files:**
- Modify: `index.html` — the mode-switch handler and `pdfAddFiles`.

**Interfaces:**
- Consumes: existing `/api/pdf/compress`, `/api/pdf/to-images`, queue plumbing.
- Produces: UI only.

- [ ] **Step 1: Enable `multiple` for compress and PDF → Images**

In the mode-switch handler, the current line is:

```javascript
  pdfFileInput.multiple = img;
```

Replace with (multiple for everything except the page-picker, which manages its own sections):

```javascript
  pdfFileInput.multiple = img || toImg || toComp;
```

- [ ] **Step 2: Stop capping to one file**

In `pdfAddFiles(fs)`, the current cap line is:

```javascript
  if (pdfMode === 'pdf2img' || pdfMode === 'compress') { pdfClearAll(); fs = fs.slice(-1); }  // one PDF at a time
```

Delete that line entirely. (Dropped PDFs now append as queue rows; the existing convert loops process each independently.)

- [ ] **Step 3: Verify**

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
echo -n "multiple wired for compress/pdf2img: "; grep -c 'img || toImg || toComp' index.html
```

Expected: each script block `ok`; the grep prints `1`. (Manual: in the browser, Compress and PDF → Images now accept several PDFs, each row converting + downloading independently.)

- [ ] **Step 4: Checkpoint**

Confirm syntax ok. `python3 test_pdf.py` unaffected.

---

### Task 4: PDF → Pages per-PDF sections (frontend)

**Files:**
- Modify: `index.html` — markup (remove the single page-range row; restyle the thumbs container), CSS (section styles), and the pages-mode JS (replace single-PDF state + helpers with a section model; rewrite the export branch to use `/api/pdf/extract-batch`).

**Interfaces:**
- Consumes: `/api/pdf/thumbnails`, `/api/pdf/extract-batch`; reuses `parsePageRanges`, `pagesToText`.
- Produces: UI only.

- [ ] **Step 1: Markup — drop the global page-range row; make the thumbs container hold sections**

Current markup block:

```html
    <div class="options-row" id="pdfPagesRow" style="display:none">
      <span class="option-label">Pages</span>
      <input type="text" id="pdfPagesInput" class="pages-input" placeholder="e.g. 1,3,5-7" />
    </div>

    <div class="options-row" id="pdfPagesOutRow" style="display:none">
      <span class="option-label">Output</span>
      <div class="fmt-group" id="pdfPagesOutGroup">
        <button class="fmt-btn active" data-combine="true">One combined PDF</button>
        <button class="fmt-btn" data-combine="false">One PDF per page</button>
      </div>
    </div>

    <div id="pdfThumbs" class="pdf-thumbs" style="display:none"></div>
```

Replace with (remove `pdfPagesRow`; change `pdfThumbs` class to `pdf-sections`):

```html
    <div class="options-row" id="pdfPagesOutRow" style="display:none">
      <span class="option-label">Output</span>
      <div class="fmt-group" id="pdfPagesOutGroup">
        <button class="fmt-btn active" data-combine="true">One combined PDF</button>
        <button class="fmt-btn" data-combine="false">One PDF per page</button>
      </div>
    </div>

    <div id="pdfThumbs" class="pdf-sections" style="display:none"></div>
```

- [ ] **Step 2: CSS — section styles**

After the existing `.pdf-thumb .pg-num { … }` rule, add:

```css
    .pdf-sections { display: flex; flex-direction: column; gap: 18px; margin-top: 14px; }
    .pdf-section-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
    .pdf-section-name { font-size: 13px; color: var(--text-muted); font-weight: 600; word-break: break-all; }
```

- [ ] **Step 3: JS — replace refs + single-PDF state**

Current refs/state lines:

```javascript
const pdfPagesRow    = document.getElementById('pdfPagesRow');
const pdfPagesOutRow = document.getElementById('pdfPagesOutRow');
const pdfPagesInput  = document.getElementById('pdfPagesInput');
const pdfThumbs      = document.getElementById('pdfThumbs');
```

Replace with (drop `pdfPagesRow`/`pdfPagesInput`):

```javascript
const pdfPagesOutRow = document.getElementById('pdfPagesOutRow');
const pdfThumbs      = document.getElementById('pdfThumbs');
```

Current state lines:

```javascript
let pdfPageCount = 0;
let pdfSelected = new Set();   // 1-based selected page numbers
let pdfCombine = true;
let pdfPagesFile = null;       // the dropped PDF File for pdf2pages
```

Replace with:

```javascript
let pdfCombine = true;
let pdfSections = [];          // [{ id, file, pageCount, selected:Set, inputEl, thumbsEl, section }]
```

- [ ] **Step 4: JS — mode switch no longer toggles the removed row**

In the mode-switch handler, the current line:

```javascript
  pdfPagesRow.style.display    = toPages ? '' : 'none';
```

Delete it. (Leave `pdfPagesOutRow` and `pdfThumbs` display lines intact.)

- [ ] **Step 5: JS — reset sections in `pdfClearAll`**

Current `pdfClearAll` tail:

```javascript
  pdfPagesFile = null;
  pdfPageCount = 0;
  pdfSelected = new Set();
  pdfThumbs.innerHTML = '';
  pdfPagesInput.value = '';
  pdfCompressHint.style.display = 'none';
  pdfCompressHint.textContent = '';
}
```

Replace with:

```javascript
  pdfSections = [];
  pdfThumbs.innerHTML = '';
  pdfCompressHint.style.display = 'none';
  pdfCompressHint.textContent = '';
}
```

- [ ] **Step 6: JS — pages branch in `pdfAddFiles` (append a section per PDF)**

Current branch:

```javascript
  if (pdfMode === 'pdf2pages') {
    const pdf = fs.find(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    if (pdf) pdfLoadPagesPdf(pdf);
    return;
  }
```

Replace with:

```javascript
  if (pdfMode === 'pdf2pages') {
    const pdfs = fs.filter(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
    pdfs.forEach(f => pdfAddPageSection(f));
    return;
  }
```

- [ ] **Step 7: JS — replace the single-PDF helpers with section helpers**

Replace this entire block (the current `parsePageRanges`/`pagesToText` stay; only the three single-PDF functions and the global input listener are replaced):

```javascript
function renderThumbSelection() {
  [...pdfThumbs.children].forEach(el => {
    const pg = +el.dataset.page;
    if (!Number.isNaN(pg)) el.classList.toggle('selected', pdfSelected.has(pg));
  });
  pdfConvertBtn.disabled = pdfSelected.size === 0;
}

function syncTextFromSelection() {
  pdfPagesInput.value = pagesToText(pdfSelected);
  renderThumbSelection();
}

async function pdfLoadPagesPdf(file) {
  pdfPagesFile = file;
  pdfThumbs.style.display = '';
  pdfThumbs.innerHTML = '<div class="drop-hint">Rendering pages…</div>';
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

pdfPagesInput.addEventListener('input', () => {
  const arr = parsePageRanges(pdfPagesInput.value, pdfPageCount);
  pdfSelected = new Set(arr);
  renderThumbSelection();
});
```

with:

```javascript
function pdfRenderSectionSelection(entry) {
  [...entry.thumbsEl.children].forEach(el => {
    const pg = +el.dataset.page;
    if (!Number.isNaN(pg)) el.classList.toggle('selected', entry.selected.has(pg));
  });
}

function pdfUpdateExportEnabled() {
  pdfConvertBtn.disabled = !pdfSections.some(s => s.selected.size > 0);
}

function pdfSyncSection(entry) {
  entry.inputEl.value = pagesToText(entry.selected);
  pdfRenderSectionSelection(entry);
  pdfUpdateExportEnabled();
}

async function pdfAddPageSection(file) {
  const id = pdfNextId++;
  const section = document.createElement('div');
  section.className = 'pdf-section';
  section.dataset.id = id;
  section.innerHTML =
    `<div class="pdf-section-head">
       <span class="pdf-section-name">${file.name}</span>
       <input type="text" class="pages-input pdf-section-pages" placeholder="e.g. 1,3,5-7" />
     </div>
     <div class="pdf-thumbs pdf-section-thumbs"><div class="drop-hint">Rendering pages…</div></div>`;
  pdfThumbs.style.display = '';
  pdfThumbs.appendChild(section);
  pdfQueue.style.display = '';

  const inputEl = section.querySelector('.pdf-section-pages');
  const thumbsEl = section.querySelector('.pdf-section-thumbs');
  const entry = { id, file, pageCount: 0, selected: new Set(), inputEl, thumbsEl, section };
  pdfSections.push(entry);

  inputEl.addEventListener('input', () => {
    entry.selected = new Set(parsePageRanges(inputEl.value, entry.pageCount));
    pdfRenderSectionSelection(entry);
    pdfUpdateExportEnabled();
  });

  const fd = new FormData();
  fd.append('file', file);
  try {
    const res = await fetch('/api/pdf/thumbnails', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to render');
    entry.pageCount = data.page_count;
    entry.selected = new Set(data.thumbnails.map(t => t.page));  // all selected by default
    thumbsEl.innerHTML = '';
    for (const t of data.thumbnails) {
      const el = document.createElement('button');
      el.className = 'pdf-thumb';
      el.dataset.page = t.page;
      el.innerHTML = `<img src="${t.dataUrl}" alt="page ${t.page}"><span class="pg-num">${t.page}</span>`;
      el.addEventListener('click', () => {
        const pg = +el.dataset.page;
        if (entry.selected.has(pg)) entry.selected.delete(pg); else entry.selected.add(pg);
        pdfSyncSection(entry);
      });
      thumbsEl.appendChild(el);
    }
    pdfSyncSection(entry);
  } catch (e) {
    thumbsEl.innerHTML = `<div class="drop-hint">Error: ${e.message}</div>`;
  }
}
```

- [ ] **Step 8: JS — rewrite the export branch to call `/api/pdf/extract-batch`**

Current `pdf2pages` branch in the `pdfConvertBtn` click handler:

```javascript
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
      const a = Object.assign(document.createElement('a'),
        { href: URL.createObjectURL(blob), download: name });
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      alert(e.message);
    } finally {
      pdfConvertBtn.disabled = pdfSelected.size === 0;
    }
    return;
  }
```

Replace with:

```javascript
  if (pdfMode === 'pdf2pages') {
    const active = pdfSections.filter(s => s.selected.size > 0);
    if (!active.length) return;
    const fd = new FormData();
    active.forEach(s => {
      fd.append('file', s.file);
      fd.append('pages', pagesToText(s.selected));
    });
    fd.append('combine', pdfCombine ? 'true' : 'false');
    pdfConvertBtn.disabled = true;
    try {
      const res = await fetch('/api/pdf/extract-batch', { method: 'POST', body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'Export failed');
      }
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename="?([^"]+)"?/);
      const name = m ? m[1] : 'pages.zip';
      const a = Object.assign(document.createElement('a'),
        { href: URL.createObjectURL(blob), download: name });
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e) {
      alert(e.message);
    } finally {
      pdfUpdateExportEnabled();
    }
    return;
  }
```

- [ ] **Step 9: Syntax-check + verify the full flow**

```bash
SP="/private/tmp/claude-501/-Users-bryglen-Work-personal-tools/692e5c0b-17ff-447c-a7ca-7d70a01af5af/scratchpad"
python3 - "$SP" <<'PY'
import re, sys, os
sp = sys.argv[1]
html = open('index.html').read()
blocks = re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.S)
for i, s in enumerate(blocks):
    open(os.path.join(sp, f"ck_{i}.js"), "w").write(s)
print("blocks", len(blocks))
# guard: no leftover references to removed single-PDF symbols
for sym in ("pdfPagesInput", "pdfPagesFile", "pdfLoadPagesPdf", "pdfSelected", "syncTextFromSelection", "renderThumbSelection"):
    assert sym not in html, f"leftover reference: {sym}"
print("no leftover single-PDF refs")
PY
for f in "$SP"/ck_*.js; do node --check "$f" && echo "$(basename "$f") ok" || echo "$(basename "$f") FAIL"; done

# end-to-end: serve, confirm page, and run the two-PDF batch the UI would issue
source image_convert/.venv/bin/activate 2>/dev/null
lsof -ti tcp:5002 | xargs kill 2>/dev/null
python3 server.py > /tmp/srv.log 2>&1 &
SERVER_PID=$!
for i in $(seq 1 20); do curl -s -o /dev/null http://localhost:5002/ && break; sleep 0.5; done
curl -s -F "file=@/tmp/a.pdf" http://localhost:5002/api/pdf/thumbnails >/dev/null && echo "thumbnails ok"
curl -s -F "file=@/tmp/a.pdf" -F "pages=1,3" -F "file=@/tmp/b.pdf" -F "pages=2" -F "combine=true" \
  http://localhost:5002/api/pdf/extract-batch -o /tmp/ui.zip
python3 -c "import zipfile; print('batch zip names', zipfile.ZipFile('/tmp/ui.zip').namelist())"
kill $SERVER_PID 2>/dev/null
```

Expected: 2 script blocks, `no leftover single-PDF refs`, each block `ok`, `thumbnails ok`, and `batch zip names ['a_extracted.pdf', 'b_extracted.pdf']`.

- [ ] **Step 10: Manual browser verification**

```bash
lsof -ti tcp:5002 | xargs kill 2>/dev/null
python3 server.py > /tmp/srv.log 2>&1 &
echo "Open http://localhost:5002 → PDF → 'PDF → Pages'"
```

Verify: drop 2+ PDFs → one section each with its own thumbnails + page box; toggling/typing in one section doesn't affect the other; Export downloads `pages.zip` containing one output per PDF; with a single PDF + combined, Export downloads a single `<stem>_extracted.pdf`. Then `kill` the server.

- [ ] **Step 11: Checkpoint**

Confirm steps 9-10; `python3 test_pdf.py` unaffected.

---

### Task 5: README

**Files:**
- Modify: `README.md` — PDF Converter section.

- [ ] **Step 1: Note multi-file support**

In the PDF Converter section, add a line (after the existing mode bullets):

```markdown
All PDF modes accept multiple PDFs at once: **Compress** and **PDF → Images** process each file independently (each gets its own download); **PDF → Pages** shows a section per PDF (independent page selection) and exports everything as one `pages.zip`.
```

- [ ] **Step 2: Checkpoint**

Run `python3 test_pdf.py` one final time — all `ok`, 0 failures.

---

## Self-Review

**Spec coverage:**
- Compress batch → Task 3. ✓
- PDF → Images batch → Task 3. ✓
- PDF → Pages per-PDF sections → Task 4 (markup/CSS/JS). ✓
- `extract_pdf_pages_batch` (unique names, combine/per-page) → Task 1 + tests. ✓
- `/api/pdf/extract-batch` (single→file, multiple→zip, per-file validation) → Task 2 + curl. ✓
- Combined `pages.zip` export → Task 2 + Task 4 Step 8. ✓
- Image/Video untouched → only `index.html` PDF code + PDF module/route changed. ✓
- README → Task 5. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete old/new code; verification steps give exact commands and expected output. ✓

**Type consistency:** `extract_pdf_pages_batch(items: list[(str,bytes,list[int])], combine) -> list[(str,bytes)]` consistent across Task 1 (def), Task 2 (route call). Frontend symbols (`pdfSections`, `pdfAddPageSection`, `pdfSyncSection`, `pdfRenderSectionSelection`, `pdfUpdateExportEnabled`) defined before use; removed symbols (`pdfPagesInput`, `pdfPagesFile`, `pdfSelected`, `pdfLoadPagesPdf`, `syncTextFromSelection`, `renderThumbSelection`) are guarded against in Task 4 Step 9. Form fields `file`/`pages`/`combine` and headers match between Task 2 (server) and Task 4 (client). ✓
