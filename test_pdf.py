"""Tests for pdf_convert.pdf_converter (needs pillow + pymupdf).
Run: python3 test_pdf.py"""

import io
import fitz
from PIL import Image
from pdf_convert.pdf_converter import (
    images_to_pdf, pdf_to_images, parse_page_ranges,
    pdf_page_count, pdf_thumbnails, extract_pdf_pages, extract_pdf_pages_batch,
    gs_available, _compress_with_python, _compress_with_ghostscript, compress_pdf,
)


def _img(w, h, color):
    return Image.new("RGB", (w, h), color)


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
    assert p1.width > p1.height
    assert p2.height > p2.width


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


def test_compress_pdf_preset_returns_valid_pdf():
    src = _noisy_pdf(pages=1)
    for q in ("small", "balanced", "high"):
        data, engine = compress_pdf(src, quality=q)
        assert data[:4] == b"%PDF"
        assert engine in ("ghostscript", "python")


def test_compress_pdf_target_met_when_achievable():
    src = _noisy_pdf(pages=2)            # ~1+ MB of noise
    # An unreachable target walks the whole ladder and returns the smallest result;
    # its size is the achievable floor for whichever engine is active.
    floor = len(compress_pdf(src, target_bytes=1)[0])
    data, engine = compress_pdf(src, target_bytes=floor)
    assert len(data) <= floor
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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
