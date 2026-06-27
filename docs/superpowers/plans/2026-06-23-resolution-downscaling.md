# Resolution Downscaling + Converter Consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a resolution-downscaling selector (Original/4K/1440p/1080p/720p/480p) to the Media Converter's image + video paths, and consolidate the duplicated converter logic so the web app and the CLI share one module per media type.

**Architecture:** A new pure module `resolution.py` holds the presets and `compute_target_size`. Image logic + CLI live in `image_convert/image_converter.py`; video logic + CLI live in `video_convert/convert_video.py`. `server.py` becomes a thin HTTP/progress layer importing both. The browser UI gains a Resolution button row per tab.

**Tech Stack:** Python 3.9+, Flask, Pillow (+ pillow-heif), FFmpeg/ffprobe (CLI subprocess), vanilla HTML/JS.

## Global Constraints

- Resolution semantics = orientation-aware bounding box, aspect-ratio preserved, **never upscale**. Presets: `2160p`=3840×2160, `1440p`=2560×1440, `1080p`=1920×1080, `720p`=1280×720, `480p`=854×480; `original`=no resize.
- Defaults: **image → `original`**, **video → `1080p`**.
- Single source of truth: presets + `compute_target_size` live only in `resolution.py`.
- Image and video stay as **separate** modules. Image module name: `image_convert/image_converter.py`. Video module name: `video_convert/convert_video.py`.
- Video output dimensions must be **even** (H.264/VP9 requirement); enforced in the video command builder, not in `compute_target_size`.
- This directory is **not a git repository**. Each task ends with a verification checkpoint instead of a commit. If you want history, run `git init` once at the start; then the optional `git` commands at each checkpoint apply. Otherwise skip them.
- All test files live at the repo root (`tools/`) and run from there: `python3 <test>.py`. They use plain `assert` + a `__main__` runner, so **no new dependency** (pytest not required).

---

## File Structure

- Create: `resolution.py` — presets + `compute_target_size` (pure).
- Create: `test_resolution.py`, `test_image.py`, `test_video.py` — root-level test runners.
- Create: `image_convert/image_converter.py` — image logic + CLI (absorbs `converter.py`).
- Delete: `image_convert/converter.py` — folded into `image_converter.py`.
- Rewrite: `video_convert/convert_video.py` — video logic (shared builder) + CLI.
- Modify: `server.py` — imports + resolution wiring; drop duplicated video logic.
- Modify: `index.html` — Resolution row + JS per tab.
- Modify: `README.md` — resolution options + shared-module note.

---

## Task 1: Shared resolution module

**Files:**
- Create: `resolution.py`
- Test: `test_resolution.py`

**Interfaces:**
- Produces: `RES_BOXES: dict[str, tuple[int,int]]`; `compute_target_size(w:int, h:int, preset:str) -> tuple[int,int] | None`.

- [ ] **Step 1: Write the failing test** — create `test_resolution.py`:

```python
"""Tests for resolution.compute_target_size.
Run: python3 test_resolution.py   (also discoverable by pytest)."""

from resolution import compute_target_size


def test_landscape_4k_to_1080p():
    assert compute_target_size(3840, 2160, "1080p") == (1920, 1080)


def test_portrait_4k_to_1080p():
    assert compute_target_size(2160, 3840, "1080p") == (1080, 1920)


def test_square_limited_by_short_edge():
    # square @1080p: long box=1920, short box=1080 → scale by 1080/3000
    assert compute_target_size(3000, 3000, "1080p") == (1080, 1080)


def test_four_by_three_to_1080p():
    # 4000x3000 @1080p: scale=min(1920/4000, 1080/3000)=0.36 → 1440x1080
    assert compute_target_size(4000, 3000, "1080p") == (1440, 1080)


def test_no_upscale_when_smaller():
    assert compute_target_size(1280, 720, "1080p") is None


def test_exact_fit_is_noop():
    assert compute_target_size(1920, 1080, "1080p") is None


def test_720p_landscape():
    assert compute_target_size(3840, 2160, "720p") == (1280, 720)


def test_original_returns_none():
    assert compute_target_size(3840, 2160, "original") is None


def test_unknown_preset_returns_none():
    assert compute_target_size(3840, 2160, "999p") is None


def test_case_insensitive_preset():
    assert compute_target_size(3840, 2160, "1080P") == (1920, 1080)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 test_resolution.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'resolution'`.

- [ ] **Step 3: Write minimal implementation** — create `resolution.py`:

```python
"""Shared resolution presets and downscale math for the image + video converters.

A preset is a (long_edge, short_edge) bounding box. Media is scaled to fit inside
the box with its long side along the box's long side, preserving aspect ratio.
Downscale only — sources that already fit are left untouched.
"""

RES_BOXES = {
    "2160p": (3840, 2160),
    "1440p": (2560, 1440),
    "1080p": (1920, 1080),
    "720p":  (1280, 720),
    "480p":  (854, 480),
}


def compute_target_size(w, h, preset):
    """Return (new_w, new_h) to fit (w, h) inside the preset box, preserving
    aspect ratio and never upscaling.

    Returns None for 'original', an unknown preset, non-positive dimensions, or
    when the source already fits the box (no-op).
    """
    box = RES_BOXES.get((preset or "").lower())
    if not box or w <= 0 or h <= 0:
        return None
    long_box, short_box = box
    if w >= h:
        max_w, max_h = long_box, short_box
    else:
        max_w, max_h = short_box, long_box
    scale = min(max_w / w, max_h / h, 1.0)
    if scale >= 1.0:
        return None
    return (round(w * scale), round(h * scale))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 test_resolution.py`
Expected: PASS — `10 passed`.

- [ ] **Step 5: Checkpoint**

Optional commit (only if `git init` was run):
```bash
git add resolution.py test_resolution.py
git commit -m "feat: add shared resolution presets + compute_target_size"
```

---

## Task 2: Consolidate image converter + add resolution

**Files:**
- Create: `image_convert/image_converter.py` (replaces the old CLI; absorbs `converter.py`)
- Delete: `image_convert/converter.py`
- Test: `test_image.py`

**Interfaces:**
- Consumes: `resolution.compute_target_size`, `resolution.RES_BOXES`.
- Produces: `convert_image(img, out_fmt, lossless=True, resolution="original") -> bytes`; module-level `OUTPUT_FORMATS`, `MIME_TYPES`, `INPUT_EXTS`; `main()` CLI.

- [ ] **Step 1: Write the failing test** — create `test_image.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 test_image.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'image_convert.image_converter'` (current file is `image_converter.py` but imports `from converter import ...`, which breaks when imported as a package; this task makes it self-contained).

- [ ] **Step 3: Write the consolidated module** — create/overwrite `image_convert/image_converter.py`:

```python
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
    base_kwargs = {}
    if exif:
        base_kwargs["exif"] = exif
    if icc:
        base_kwargs["icc_profile"] = icc

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
        img.save(buf, format="AVIF", quality=100, **base_kwargs)
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
```

- [ ] **Step 4: Delete the old logic module**

Run: `rm image_convert/converter.py`
(Its contents are now in `image_converter.py`. `server.py` is repointed in Task 4.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 test_image.py`
Expected: PASS — `3 passed`.

- [ ] **Step 6: Checkpoint**

Optional commit:
```bash
git add image_convert/image_converter.py test_image.py
git rm image_convert/converter.py
git commit -m "feat: consolidate image converter + add resolution downscale"
```

---

## Task 3: Consolidate video converter + add resolution

**Files:**
- Rewrite: `video_convert/convert_video.py`
- Test: `test_video.py`

**Interfaces:**
- Consumes: `resolution.compute_target_size`, `resolution.RES_BOXES`.
- Produces: `build_ffmpeg_cmd(input_path, output_path, fmt="mp4", speed=1.0, quality="balanced", resolution="1080p", dims=None, use_nvenc=False) -> list[str]`; `probe_dimensions(path) -> tuple[int,int]|None`; `speed_filters(speed) -> (str,str)`; `VIDEO_MIME`, `CRF_MAP`, `CQ_MAP`, `VIDEO_EXTS`; `main()` CLI.

- [ ] **Step 1: Write the failing test** — create `test_video.py`:

```python
"""Tests for video_convert.convert_video.build_ffmpeg_cmd (dims passed in, so no
ffprobe/ffmpeg needed). Run: python3 test_video.py"""

from video_convert.convert_video import build_ffmpeg_cmd


def _joined(**kw):
    return " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(3840, 2160), **kw))


def test_scale_filter_added_for_1080p():
    assert "scale=1920:1080:flags=lanczos" in _joined(resolution="1080p")


def test_no_scale_for_original():
    assert "scale=" not in _joined(resolution="original")


def test_no_scale_when_no_upscale():
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(1280, 720), resolution="1080p"))
    assert "scale=" not in cmd


def test_even_dimensions_enforced():
    # 1003x750 @720p → scale=0.96 → (963, 720); 963 is odd → forced down to 962
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(1003, 750), resolution="720p"))
    assert "scale=962:720:flags=lanczos" in cmd


def test_libx264_default():
    assert "libx264" in _joined(resolution="original")


def test_webm_uses_vp9():
    assert "libvpx-vp9" in _joined(fmt="webm", resolution="original")


def test_nvenc_when_requested():
    assert "h264_nvenc" in _joined(fmt="mp4", resolution="original", use_nvenc=True)


def test_quality_maps_to_crf():
    assert "-crf 18" in _joined(fmt="mp4", quality="nearlossless", resolution="original")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 test_video.py`
Expected: FAIL — `ImportError: cannot import name 'build_ffmpeg_cmd'` (the current file only has `run_ffmpeg`).

- [ ] **Step 3: Rewrite the module** — overwrite `video_convert/convert_video.py`:

```python
"""Video conversion logic + interactive batch CLI.

Imported by the web server (build_ffmpeg_cmd, VIDEO_MIME) and runnable
standalone: python video_convert/convert_video.py
"""
import re
import shlex
import subprocess
import sys
from pathlib import Path

# Make the repo-root shared module importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resolution import compute_target_size, RES_BOXES  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
VIDEO_MIME = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}
CRF_MAP = {"nearlossless": 18, "balanced": 23, "small": 28}
CQ_MAP = {"nearlossless": 20, "balanced": 33, "small": 43}


def has_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False


def has_nvenc():
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                capture_output=True, text=True, check=True)
        return "h264_nvenc" in result.stdout
    except Exception:
        return False


def probe_dimensions(path):
    """Return (width, height) of the first video stream, or None on any failure."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
            capture_output=True, text=True, check=True,
        )
        m = re.match(r"\s*(\d+)x(\d+)", out.stdout.strip())
        return (int(m[1]), int(m[2])) if m else None
    except Exception:
        return None


def speed_filters(speed):
    """Return (video_filter, audio_filter) for a playback-speed change."""
    vf = f"setpts={1 / speed:.6f}*PTS"
    parts, r = [], speed
    while r > 2.0:
        parts.append("atempo=2.0"); r /= 2.0
    while r < 0.5:
        parts.append("atempo=0.5"); r /= 0.5
    parts.append(f"atempo={r:.6f}".rstrip("0").rstrip("."))
    return vf, ",".join(parts)


def _scale_filter(input_path, resolution, dims):
    if dims is None:
        dims = probe_dimensions(input_path)
    target = compute_target_size(*dims, resolution) if dims else None
    if not target:
        return None
    w, h = target
    w -= w % 2
    h -= h % 2
    return f"scale={w}:{h}:flags=lanczos"


def build_ffmpeg_cmd(input_path, output_path, fmt="mp4", speed=1.0,
                     quality="balanced", resolution="1080p", dims=None,
                     use_nvenc=False):
    """Build the ffmpeg command shared by the web server and the CLI.

    dims: pass (w, h) to skip the ffprobe call (used in tests); otherwise probed.
    """
    vf_parts = []
    scale = _scale_filter(input_path, resolution, dims)
    if scale:
        vf_parts.append(scale)
    vf_speed, af = speed_filters(speed)
    vf_parts.append(vf_speed)
    vf = ",".join(vf_parts)

    if fmt == "webm":
        cq = CQ_MAP.get(quality, 33)
        codec = ["-c:v", "libvpx-vp9", "-cq", str(cq), "-b:v", "0",
                 "-c:a", "libopus", "-b:a", "128k"]
    else:
        crf = CRF_MAP.get(quality, 23)
        if use_nvenc:
            codec = ["-c:v", "h264_nvenc", "-cq", str(crf), "-preset", "p4",
                     "-c:a", "aac", "-b:a", "128k"]
        else:
            codec = ["-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
                     "-c:a", "aac", "-b:a", "128k"]

    return ["ffmpeg", "-y", "-i", str(input_path), "-vf", vf,
            *codec, "-af", af, str(output_path)]


# ── CLI ──────────────────────────────────────────────────────────────────────

RES_CHOICES = ["original"] + list(RES_BOXES.keys())
FMT_CHOICES = ["mp4", "webm", "mov"]
QUALITY_CHOICES = ["nearlossless", "balanced", "small"]


def get_video_files(path):
    if path.is_file():
        return [path] if path.suffix.lower() in VIDEO_EXTS else []
    if path.is_dir():
        return sorted(p for p in path.iterdir()
                      if p.is_file() and p.suffix.lower() in VIDEO_EXTS)
    return []


def build_output_name(input_path, fmt, speed):
    speed_tag = f"_{speed}x" if speed != 1.0 else ""
    return input_path.with_name(f"{input_path.stem}_converted{speed_tag}.{fmt}")


def ask_yes_no(prompt, default=False):
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input(prompt + suffix).strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def ask_choice(prompt, choices, default):
    while True:
        raw = input(f"{prompt} ({'/'.join(choices)}) [{default}]: ").strip().lower()
        if not raw:
            return default
        if raw in choices:
            return raw
        print("Invalid choice.")


def ask_speed():
    if not ask_yes_no("Change playback speed?", default=False):
        return 1.0
    while True:
        raw = input("Enter speed (e.g. 1.25, 1.5, 2): ").strip()
        try:
            speed = float(raw)
            if speed <= 0:
                print("Speed must be greater than 0."); continue
            return speed
        except ValueError:
            print("Please enter a valid number.")


def main():
    if not has_ffmpeg():
        print("FFmpeg is not installed or not found in PATH.")
        return

    raw = input("Enter file or folder path: ").strip().strip('"').strip("'")
    source = Path(raw).expanduser()
    if not source.exists():
        print("Path not found."); return

    files = get_video_files(source)
    if not files:
        print("No supported video files found."); return

    fmt = ask_choice("Output format", FMT_CHOICES, "mp4")
    quality = ask_choice("Quality", QUALITY_CHOICES, "balanced")
    resolution = ask_choice("Resolution", RES_CHOICES, "1080p")
    speed = ask_speed()

    use_nvenc = False
    if fmt != "webm" and has_nvenc():
        use_nvenc = ask_yes_no("NVIDIA NVENC detected. Use GPU encoding?", default=True)

    encoder = "libvpx-vp9" if fmt == "webm" else ("h264_nvenc" if use_nvenc else "libx264")
    print(f"\nFound {len(files)} video(s). {fmt} @ {resolution}, quality={quality}, "
          f"speed={speed}x, encoder={encoder}")

    success = 0
    for f in files:
        output_file = build_output_name(f, fmt, speed)
        cmd = build_ffmpeg_cmd(f, output_file, fmt=fmt, speed=speed,
                               quality=quality, resolution=resolution, use_nvenc=use_nvenc)
        print(f"\nConverting: {f.name}")
        print(" ".join(shlex.quote(x) for x in cmd))
        if subprocess.run(cmd).returncode == 0:
            success += 1
            print(f"Done: {output_file.name}")
        else:
            print(f"Failed: {f.name}")

    print(f"\nFinished. {success}/{len(files)} converted.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 test_video.py`
Expected: PASS — `8 passed`.

- [ ] **Step 5: Checkpoint**

Optional commit:
```bash
git add video_convert/convert_video.py test_video.py
git commit -m "feat: consolidate video converter + add resolution downscale"
```

---

## Task 4: Wire server.py to the shared converters

**Files:**
- Modify: `server.py`

**Interfaces:**
- Consumes: `image_convert.image_converter.convert_image/OUTPUT_FORMATS/MIME_TYPES`; `video_convert.convert_video.build_ffmpeg_cmd/VIDEO_MIME`.

- [ ] **Step 1: Replace the import block** (`server.py:1-13`)

Replace lines 1–13 with:

```python
import io, sys, re, uuid, shutil, threading, subprocess, tempfile
from pathlib import Path
from flask import Flask, request, send_file, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parent))
from image_convert.image_converter import convert_image, OUTPUT_FORMATS, MIME_TYPES
from video_convert.convert_video import build_ffmpeg_cmd, VIDEO_MIME
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

app = Flask(__name__, static_folder=".")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB
```

- [ ] **Step 2: Add resolution to the image route**

In `image_convert()` (the `/api/image/convert` handler), after the `lossless = ...` line add:

```python
    resolution = request.form.get("resolution", "original").lower()
```

and change the conversion call from `data = convert_image(img, out_fmt, lossless=lossless)` to:

```python
        data = convert_image(img, out_fmt, lossless=lossless, resolution=resolution)
```

- [ ] **Step 3: Delete the now-duplicated video constants/helpers**

Remove these from `server.py` (now provided by `convert_video.py`): the `VIDEO_MIME`, `CRF_MAP`, `CQ_MAP` module constants and the entire `_speed_filters` function. **Keep** `_parse_duration` and `_parse_time` (server-only progress parsing).

- [ ] **Step 4: Rewrite `_run_video_job` to use the shared builder**

Replace the whole `_run_video_job` function with:

```python
def _run_video_job(job_id, input_path, output_path, out_fmt, speed, quality, resolution):
    cmd = build_ffmpeg_cmd(input_path, output_path, fmt=out_fmt, speed=speed,
                           quality=quality, resolution=resolution, use_nvenc=False)
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)
    duration = None

    for line in proc.stderr:
        if duration is None:
            d = _parse_duration(line)
            if d:
                duration = d
        t = _parse_time(line)
        if t is not None and duration:
            with _jobs_lock:
                if job_id in _jobs:
                    _jobs[job_id]["progress"] = min(99, int(t / duration * 100))

    proc.wait()
    with _jobs_lock:
        if job_id not in _jobs:
            return
        if proc.returncode == 0:
            _jobs[job_id].update(status="done", progress=100, after_size=output_path.stat().st_size)
        else:
            _jobs[job_id].update(status="error", error="FFmpeg conversion failed")
```

- [ ] **Step 5: Pass resolution through the video route**

In `video_convert()` (the `/api/video/convert` handler), after `quality = request.form.get("quality", "balanced")` add:

```python
    resolution = request.form.get("resolution", "1080p").lower()
```

and update the thread spawn args to include it:

```python
    threading.Thread(
        target=_run_video_job,
        args=(job_id, input_path, output_path, out_fmt, speed, quality, resolution),
        daemon=True,
    ).start()
```

- [ ] **Step 6: Smoke-test the server imports + image endpoint**

Run:
```bash
python3 - <<'PY'
import io
from PIL import Image
import server
c = server.app.test_client()
buf = io.BytesIO(); Image.new("RGB", (3840, 2160), (1, 2, 3)).save(buf, "PNG"); buf.seek(0)
r = c.post("/api/image/convert", data={"format": "jpg", "resolution": "1080p",
           "file": (buf, "x.png")}, content_type="multipart/form-data")
print("status", r.status_code)
out = Image.open(io.BytesIO(r.data))
print("size", out.size)
assert r.status_code == 200 and out.size == (1920, 1080)
print("OK")
PY
```
Expected: `status 200`, `size (1920, 1080)`, `OK`.

- [ ] **Step 7: Checkpoint**

Optional commit:
```bash
git add server.py
git commit -m "refactor: server uses shared converters + resolution"
```

---

## Task 5: Add the Resolution selector to the UI

**Files:**
- Modify: `index.html`

- [ ] **Step 1: Add the image Resolution row**

In the IMAGE tab, immediately AFTER the closing `</div>` of the format `.options-row` (the one containing `imgFmtGroup` / `imgLosslessWrap`, ending at `index.html:232`) and BEFORE `<div class="queue" id="imgQueue" ...>`, insert:

```html
    <div class="options-row">
      <span class="option-label">Resolution</span>
      <div class="fmt-group" id="imgResGroup">
        <button class="fmt-btn active" data-res="original">Original</button>
        <button class="fmt-btn" data-res="2160p">4K</button>
        <button class="fmt-btn" data-res="1440p">1440p</button>
        <button class="fmt-btn" data-res="1080p">1080p</button>
        <button class="fmt-btn" data-res="720p">720p</button>
        <button class="fmt-btn" data-res="480p">480p</button>
      </div>
    </div>
```

- [ ] **Step 2: Add the video Resolution row**

In the VIDEO tab, immediately AFTER the Quality `.options-row` (the one containing `vidQualGroup`) and BEFORE `<div class="queue" id="vidQueue" ...>`, insert:

```html
    <div class="options-row">
      <span class="option-label">Resolution</span>
      <div class="fmt-group" id="vidResGroup">
        <button class="fmt-btn" data-res="original">Original</button>
        <button class="fmt-btn" data-res="2160p">4K</button>
        <button class="fmt-btn" data-res="1440p">1440p</button>
        <button class="fmt-btn active" data-res="1080p">1080p</button>
        <button class="fmt-btn" data-res="720p">720p</button>
        <button class="fmt-btn" data-res="480p">480p</button>
      </div>
    </div>
```

- [ ] **Step 3: Wire the image picker + send the field**

In the image converter `<script>` section: change `let imgFmt = 'jpg', imgFiles = [], imgNextId = 0;` to add `imgRes`:

```javascript
let imgFmt = 'jpg', imgRes = 'original', imgFiles = [], imgNextId = 0;
```

After the existing `makeOptionPicker(document.getElementById('imgFmtGroup'), ...)` block, add:

```javascript
makeOptionPicker(document.getElementById('imgResGroup'), btn => { imgRes = btn.dataset.res; });
```

In `imgConvert`, after `form.append('lossless', ...)`, add:

```javascript
  form.append('resolution', imgRes);
```

- [ ] **Step 4: Wire the video picker + send the field**

In the video converter `<script>` section: change `let vidFmt = 'mp4', vidSpeed = '1', vidQuality = 'balanced';` to add `vidRes`:

```javascript
let vidFmt = 'mp4', vidSpeed = '1', vidQuality = 'balanced', vidRes = '1080p';
```

After the existing `makeOptionPicker(document.getElementById('vidQualGroup'), ...)` line, add:

```javascript
makeOptionPicker(document.getElementById('vidResGroup'), btn => { vidRes = btn.dataset.res; });
```

In `vidConvert`, after `form.append('quality', vidQuality);`, add:

```javascript
    form.append('resolution', vidRes);
```

- [ ] **Step 5: Manual UI verification**

Run: `./start.sh` (opens http://localhost:5002). In the browser:
1. Image tab → drop a 4K image → set Resolution = 1080p → Convert all → Download → confirm the saved file is 1920×1080 (or 1080×1920 if portrait) and smaller.
2. Image tab → Resolution = Original → confirm output keeps original dimensions.
3. Video tab → drop a 4K video → Resolution = 720p → Convert all → confirm output is 720p and smaller.
Stop with `./stop.sh`.

- [ ] **Step 6: Checkpoint**

Optional commit:
```bash
git add index.html
git commit -m "feat: resolution selector in the web UI"
```

---

## Task 6: Update README + full verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the Image/Video sections + CLI usage**

In `README.md`:
- Under **Image Converter**, add a bullet: `- Optional downscaling: Original, 4K, 1440p, 1080p, 720p, 480p (aspect ratio preserved, never upscales)`.
- Under **Video Converter**, replace `- Downscales to 1080p, maintains aspect ratio` with `- Selectable resolution: Original, 4K, 1440p, 1080p, 720p, 480p (aspect ratio preserved, never upscales; default 1080p)`.
- Under **CLI Tools**, update the commands to:

```bash
# Image — batch convert a file or folder
python3 image_convert/image_converter.py

# Video — compress / resize / speed-adjust a file or folder
python3 video_convert/convert_video.py
```

- In **Project Structure**, replace the `converter.py` / `image_converter.py` lines and add the new layout:

```
tools/
├── server.py               # Flask server (port 5002) — thin HTTP layer
├── resolution.py           # shared resolution presets + compute_target_size
├── index.html              # Tabbed web UI
├── image_convert/
│   └── image_converter.py  # image logic + CLI (shared with server)
└── video_convert/
    └── convert_video.py    # video logic + CLI (shared with server)
```

- [ ] **Step 2: Run the full test suite**

Run:
```bash
python3 test_resolution.py && python3 test_image.py && python3 test_video.py
```
Expected: all three print their `N passed` lines with no errors.

- [ ] **Step 3: Final end-to-end check**

Run `./start.sh`, convert one image and one video at a non-Original resolution, confirm downloads have the expected dimensions and reduced size, then `./stop.sh`. Run each CLI once against a sample file and confirm the new Resolution prompt appears and output dimensions are correct.

- [ ] **Step 4: Checkpoint**

Optional commit:
```bash
git add README.md
git commit -m "docs: document resolution options + consolidated converters"
```

---

## Notes for the implementer

- Run all `python3` commands from the repo root (`tools/`). The converters add the repo root to `sys.path` themselves, so the CLIs also work when launched from elsewhere.
- HEIC/AVIF input/output requires `pillow-heif`; it's already a dependency and registered on import.
- If `ffprobe` is missing, video falls back to no-resize (by design) — don't treat that as a failure.
