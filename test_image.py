"""Tests for image_convert.image_converter.convert_image resizing and metadata.
Run: python3 test_image.py"""

import io
from PIL import Image
from image_convert.image_converter import convert_image


def test_downscales_to_1080p():
    img = Image.new("RGB", (3840, 2160), (120, 60, 200))
    out = Image.open(io.BytesIO(convert_image(img, "png", resolution="1080p")))
    assert out.size == (1920, 1080)


def test_original_keeps_size():
    img = Image.new("RGB", (3840, 2160), (10, 20, 30))
    out = Image.open(io.BytesIO(convert_image(img, "png", resolution="original")))
    assert out.size == (3840, 2160)


def test_no_upscale():
    img = Image.new("RGB", (1280, 720), (5, 5, 5))
    out = Image.open(io.BytesIO(convert_image(img, "png", resolution="1080p")))
    assert out.size == (1280, 720)


def _jpeg_with_exif(tag_value="TestDescription"):
    exif = Image.Exif()
    exif[0x010e] = tag_value  # ImageDescription
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, format="JPEG", exif=exif.tobytes())
    buf.seek(0)
    img = Image.open(buf)
    img.load()
    return img


def test_exif_preserved_jpeg_to_jpeg():
    src = _jpeg_with_exif("OriginalDescription")
    out = Image.open(io.BytesIO(convert_image(src, "jpg")))
    assert out.getexif().get(0x010e) == "OriginalDescription"


def test_exif_preserved_jpeg_to_png():
    src = _jpeg_with_exif("PngDescription")
    out = Image.open(io.BytesIO(convert_image(src, "png")))
    assert out.getexif().get(0x010e) == "PngDescription"


def test_exif_preserved_jpeg_to_webp():
    src = _jpeg_with_exif("WebpDescription")
    out = Image.open(io.BytesIO(convert_image(src, "webp")))
    assert out.getexif().get(0x010e) == "WebpDescription"


def test_icc_profile_preserved_png():
    fake_icc = b"\x00" * 4 + b"acsp" + b"\x00" * 120
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, format="PNG", icc_profile=fake_icc)
    buf.seek(0)
    src = Image.open(buf)
    src.load()
    out = Image.open(io.BytesIO(convert_image(src, "png")))
    assert out.info.get("icc_profile") == fake_icc


def test_icc_profile_preserved_jpeg():
    fake_icc = b"\x00" * 4 + b"acsp" + b"\x00" * 120
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, format="PNG", icc_profile=fake_icc)
    buf.seek(0)
    src = Image.open(buf)
    src.load()
    out = Image.open(io.BytesIO(convert_image(src, "jpg")))
    assert out.info.get("icc_profile") == fake_icc


def test_xmp_preserved_webp():
    xmp = b'<?xpacket begin=""><x:xmpmeta xmlns:x="adobe:ns:meta/"></x:xmpmeta>'
    img = Image.new("RGB", (100, 100))
    img.info["xmp"] = xmp
    out = Image.open(io.BytesIO(convert_image(img, "webp")))
    assert out.info.get("xmp") is not None


def test_no_metadata_converts_cleanly():
    img = Image.new("RGB", (100, 100), (128, 128, 128))
    out = Image.open(io.BytesIO(convert_image(img, "jpg")))
    assert out.size == (100, 100)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
