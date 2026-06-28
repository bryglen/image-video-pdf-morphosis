"""Image conversion logic + interactive batch CLI.

Imported by the web server (convert_image, OUTPUT_FORMATS, MIME_TYPES) and
runnable standalone: python image_convert/image_converter.py
"""
import io
import sys
from pathlib import Path

from PIL import Image
from pillow_heif import register_heif_opener

# Make the repo-root shared module importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resolution import compute_target_size, RES_BOXES  # noqa: E402

register_heif_opener()

INPUT_EXTS = {
    ".heic", ".heif", ".avif", ".webp", ".jpg", ".jpeg", ".png",
    ".tif", ".tiff", ".bmp", ".gif",
}

OUTPUT_FORMATS = {"png", "jpg", "jpeg", "webp", "tiff", "bmp", "heic", "heif", "avif"}

MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "tiff": "image/tiff", "bmp": "image/bmp",
    "heic": "image/heic", "heif": "image/heif", "avif": "image/avif",
}


def flatten_alpha_to_white(img):
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        alpha = img.getchannel("A") if "A" in img.getbands() else None
        bg.paste(img, mask=alpha)
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def normalize_mode(img, out_fmt):
    if out_fmt in {"jpg", "jpeg", "bmp"}:
        return flatten_alpha_to_white(img)
    return img


def convert_image(img, out_fmt, lossless=True, resolution="original"):
    """Convert a PIL image to out_fmt and return raw bytes.

    resolution: a resolution.RES_BOXES key or 'original'. Downscales with LANCZOS
    before encoding; never upscales.
    """
    target = compute_target_size(img.width, img.height, resolution)
    if target:
        img = img.resize(target, Image.LANCZOS)

    exif = img.info.get("exif")
    icc = img.info.get("icc_profile")
    xmp = img.info.get("xmp")
    base_kwargs = {}
    if exif:
        base_kwargs["exif"] = exif
    if icc:
        base_kwargs["icc_profile"] = icc
    if xmp:
        base_kwargs["xmp"] = xmp

    img = normalize_mode(img, out_fmt)
    buf = io.BytesIO()

    if out_fmt == "png":
        img.save(buf, format="PNG", **base_kwargs)
    elif out_fmt == "tiff":
        img.save(buf, format="TIFF", compression="tiff_lzw", **base_kwargs)
    elif out_fmt == "bmp":
        img.save(buf, format="BMP")
    elif out_fmt in {"jpg", "jpeg"}:
        img.save(buf, format="JPEG", quality=95, subsampling=0, optimize=True, **base_kwargs)
    elif out_fmt == "webp":
        if lossless:
            img.save(buf, format="WEBP", lossless=True, method=6, **base_kwargs)
        else:
            img.save(buf, format="WEBP", quality=95, method=6, **base_kwargs)
    elif out_fmt in {"heic", "heif"}:
        img.save(buf, format="HEIF", quality=-1, chroma=444, **base_kwargs)
    elif out_fmt == "avif":
        # AVIF is far more efficient than PNG; quality=100 produced files larger
        # than the source. 63 is near-transparent visually with real size savings.
        img.save(buf, format="AVIF", quality=63, **base_kwargs)
    else:
        raise ValueError(f"Unsupported format: {out_fmt}")

    return buf.getvalue()


# ── CLI ──────────────────────────────────────────────────────────────────────

RES_CHOICES = ["original"] + list(RES_BOXES.keys())


def ask_path():
    raw = input("Enter image file or folder path: ").strip().strip('"').strip("'")
    path = Path(raw).expanduser()
    if not path.exists():
        raise FileNotFoundError("Path not found.")
    return path


def ask_output_format():
    while True:
        fmt = input("Convert to (png/jpg/jpeg/webp/tiff/bmp/heic/heif/avif): ").strip().lower()
        if fmt in OUTPUT_FORMATS:
            return fmt
        print("Unsupported format.")


def ask_choice(prompt, choices, default):
    while True:
        raw = input(f"{prompt} ({'/'.join(choices)}) [{default}]: ").strip().lower()
        if not raw:
            return default
        if raw in choices:
            return raw
        print("Invalid choice.")


def ask_yes_no(prompt, default=False):
    suffix = " [Y/n]: " if default else " [y/N]: "
    ans = input(prompt + suffix).strip().lower()
    if not ans:
        return default
    return ans in {"y", "yes"}


def collect_inputs(path):
    if path.is_file():
        return [path] if path.suffix.lower() in INPUT_EXTS else []
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix.lower() in INPUT_EXTS)


def make_output_path(src, out_fmt):
    ext = ".jpg" if out_fmt == "jpeg" else f".{out_fmt}"
    return src.with_name(f"{src.stem}_converted{ext}")


def main():
    try:
        source = ask_path()
        out_fmt = ask_output_format()
        resolution = ask_choice("Resolution", RES_CHOICES, "original")
        files = collect_inputs(source)
        if not files:
            print("No supported image files found.")
            return

        lossless = True
        if out_fmt == "webp":
            lossless = ask_yes_no("Use lossless WEBP?", default=True)
        overwrite = ask_yes_no("Overwrite existing files?", default=False)

        print(f"\nFound {len(files)} image(s). Converting to {out_fmt} @ {resolution}...\n")
        success = 0
        for src in files:
            dst = make_output_path(src, out_fmt)
            if dst.exists() and not overwrite:
                print(f"Skipping: {dst.name}")
                continue
            try:
                with Image.open(src) as img:
                    img.load()
                    data = convert_image(img, out_fmt, lossless=lossless, resolution=resolution)
                before = src.stat().st_size
                dst.write_bytes(data)
                after = len(data)
                saved = ((before - after) / before * 100) if before else 0
                success += 1
                print(f"✔ {src.name} → {dst.name}  ({before//1024}KB → {after//1024}KB, {saved:.1f}% saved)")
            except Exception as e:
                print(f"✖ Failed: {src.name} ({e})")
        print(f"\nDone: {success}/{len(files)} converted.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
