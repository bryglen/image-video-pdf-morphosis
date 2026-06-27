"""Tests for image_convert.image_converter.convert_image resizing.
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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
