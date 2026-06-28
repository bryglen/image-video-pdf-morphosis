"""Tests for image_convert.image_converter.convert_image resizing and metadata.
Run: python3 test_image.py"""

import io
from PIL import Image
from image_convert.image_converter import convert_image, probe_image_metadata


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


def test_probe_basic_dimensions_and_format():
    buf = io.BytesIO()
    Image.new("RGB", (640, 480)).save(buf, format="PNG")
    buf.seek(0)
    img = Image.open(buf); img.load()
    meta = probe_image_metadata(img)
    assert meta["dimensions"] == "640x480"
    assert meta["format"] == "PNG"


def _exif_image():
    exif = Image.Exif()
    exif[0x010F] = "Apple"                       # Make
    exif[0x0110] = "iPhone 16 Pro"               # Model
    exif[0x0132] = "2026:03:20 18:59:31"         # DateTime
    exif[0x8825] = {1: "N", 2: (14.0, 41.0, 49.9), 3: "E", 4: (121.0, 3.0, 29.1)}  # GPS
    buf = io.BytesIO()
    Image.new("RGB", (100, 100)).save(buf, format="JPEG", exif=exif.tobytes())
    buf.seek(0)
    img = Image.open(buf); img.load()
    return img


def test_probe_extracts_camera_and_date():
    meta = probe_image_metadata(_exif_image())
    assert meta["make"] == "Apple"
    assert meta["model"] == "iPhone 16 Pro"
    assert meta["creation_time"] == "2026-03-20 18:59:31"  # EXIF "YYYY:MM:DD" -> ISO date


def test_probe_extracts_gps_as_decimal():
    meta = probe_image_metadata(_exif_image())
    assert "location" in meta
    # 14 + 41/60 + 49.9/3600 ≈ 14.6972 ; 121 + 3/60 + 29.1/3600 ≈ 121.0581
    assert meta["location"].startswith("+14.697")
    assert "+121.058" in meta["location"]


def test_probe_no_exif_is_safe():
    img = Image.new("RGB", (50, 50))
    meta = probe_image_metadata(img)
    assert meta["dimensions"] == "50x50"
    assert "make" not in meta and "location" not in meta


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
