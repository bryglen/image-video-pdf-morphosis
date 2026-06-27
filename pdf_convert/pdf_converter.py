"""Image ⇄ PDF conversion logic + interactive batch CLI.

Imported by the web server (images_to_pdf, pdf_to_images) and runnable
standalone: python pdf_convert/pdf_converter.py
"""
import io
import sys
import shutil
import subprocess
import tempfile
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


def _pdfsettings_for_dpi(dpi):
    """Map a DPI to a Ghostscript -dPDFSETTINGS preset (used by the target ladder)."""
    if dpi <= 100:
        return "/screen"
    if dpi <= 200:
        return "/ebook"
    return "/printer"


def _compress_with_ghostscript(pdf_bytes, dpi, jpeg_quality, pdfsettings="/ebook"):
    """Compress via Ghostscript (preserves text/vectors). Raises RuntimeError on failure."""
    with tempfile.TemporaryDirectory() as d:
        inp = Path(d) / "in.pdf"
        outp = Path(d) / "out.pdf"
        inp.write_bytes(pdf_bytes)
        cmd = [
            "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={pdfsettings}",
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

    def run(dpi, q, pdfsettings):
        if use_gs:
            try:
                data = _compress_with_ghostscript(pdf_bytes, dpi, q, pdfsettings)
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
            last = run(dpi, q, _pdfsettings_for_dpi(dpi))
            if len(last) <= target_bytes:
                return last, state["engine"]
        return last, state["engine"]

    preset = COMPRESS_PRESETS[quality]
    return run(preset["dpi"], preset["q"], preset["gs"]), state["engine"]


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


def main():
    raw = input("Direction (1 = images→PDF, 2 = PDF→images, 3 = extract pages, 4 = compress): ").strip()
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
    else:
        print("Invalid direction.")


if __name__ == "__main__":
    main()
