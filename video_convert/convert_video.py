"""Video conversion logic + interactive batch CLI.

Imported by the web server (build_ffmpeg_cmd, VIDEO_MIME) and runnable
standalone: python video_convert/convert_video.py
"""
import json
import re
import shlex
import struct
import subprocess
import sys
from pathlib import Path

# Make the repo-root shared module importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resolution import compute_target_size, RES_BOXES  # noqa: E402

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
VIDEO_MIME = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime"}
CRF_MAP = {"nearlossless": 18, "balanced": 23, "small": 28}
HEVC_CRF_MAP = {"nearlossless": 22, "balanced": 28, "small": 32}  # x265 CRF runs higher than x264 for equal quality
CQ_MAP  = {"nearlossless": 20, "balanced": 33, "small": 43}
VQ_MAP  = {"nearlossless": 85, "balanced": 65, "small": 40}  # VideoToolbox -q:v (0-100)


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


def has_videotoolbox():
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                capture_output=True, text=True, check=True)
        return "h264_videotoolbox" in result.stdout
    except Exception:
        return False


def has_hevc_videotoolbox():
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                capture_output=True, text=True, check=True)
        return "hevc_videotoolbox" in result.stdout
    except Exception:
        return False


def has_hevc_encoder():
    """True if FFmpeg has any HEVC encoder (libx265, hevc_videotoolbox, or hevc_nvenc)."""
    try:
        result = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                capture_output=True, text=True, check=True)
        return any(e in result.stdout for e in ("libx265", "hevc_videotoolbox", "hevc_nvenc"))
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


def probe_has_audio(path):
    """Return True if the file has at least one audio stream.

    On any probe failure, assume True — silently dropping audio is worse than
    a rare failure, and ffprobe failing usually means ffmpeg will surface it too.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        )
        return bool(out.stdout.strip())
    except Exception:
        return True


def probe_creation_time(path):
    """Return the creation_time tag string from the source container, or None."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        val = out.stdout.strip()
        return val if val else None
    except Exception:
        return None


def probe_metadata(path):
    """Return a dict of human-relevant metadata for a video, or {} on failure.

    Keys (any may be absent): creation_time, location, make, model,
    dimensions, duration (float seconds), codec, size (bytes).
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
    except Exception:
        return {}

    fmt = data.get("format", {})
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)

    meta = {}
    # Prefer Apple's local-timezone creationdate; fall back to standard UTC creation_time.
    if tags.get("com.apple.quicktime.creationdate"):
        meta["creation_time"] = tags["com.apple.quicktime.creationdate"]
    elif tags.get("creation_time"):
        meta["creation_time"] = tags["creation_time"]

    loc = tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
    if loc:
        meta["location"] = loc
    if tags.get("com.apple.quicktime.make"):
        meta["make"] = tags["com.apple.quicktime.make"]
    if tags.get("com.apple.quicktime.model"):
        meta["model"] = tags["com.apple.quicktime.model"]

    dur = fmt.get("duration")
    if dur:
        try:
            meta["duration"] = float(dur)
        except ValueError:
            pass
    size = fmt.get("size")
    if size:
        try:
            meta["size"] = int(size)
        except ValueError:
            pass
    if vstream:
        w, h = vstream.get("width"), vstream.get("height")
        if w and h:
            meta["dimensions"] = f"{w}x{h}"
        if vstream.get("codec_name"):
            meta["codec"] = vstream["codec_name"]
    return meta


# ── Apple/QuickTime metadata preservation ────────────────────────────────────
#
# iPhone videos store GPS as the key com.apple.quicktime.location.ISO6709 in the
# *moov-level* `meta` box (moov → meta → keys/ilst). macOS Spotlight/Photos read
# location only from there. FFmpeg, even with -map_metadata 0 -movflags
# use_metadata_tags, writes those custom keys to moov → udta → meta instead, which
# Apple ignores — so the converted file shows no location.
#
# The fix: lift the source's moov-level `meta` box verbatim and append it as the
# output moov's last child. The box is self-contained (a key index + values, no
# byte-offset references), so a verbatim copy is portable across containers.
# Verified with `mdimport -t` (the importer macOS actually runs).

def _read_atom_header(f):
    """Read an atom header at the current position. Return (size, type, header_len)
    or None at EOF/truncation. Handles 64-bit extended sizes (size==1)."""
    hdr = f.read(8)
    if len(hdr) < 8:
        return None
    size = struct.unpack(">I", hdr[:4])[0]
    typ = hdr[4:8]
    hl = 8
    if size == 1:  # 64-bit size follows the type
        ext = f.read(8)
        if len(ext) < 8:
            return None
        size = struct.unpack(">Q", ext)[0]
        hl = 16
    return size, typ, hl


def _find_top_atom(f, want, file_size):
    """Return (offset, size, header_len) of the first top-level atom of type
    `want`, or None. Seeks only over atom headers — never reads payloads."""
    f.seek(0)
    while f.tell() < file_size:
        off = f.tell()
        h = _read_atom_header(f)
        if h is None:
            break
        size, typ, hl = h
        if size <= 0:  # size 0 means "extends to EOF"
            size = file_size - off
        if typ == want:
            return off, size, hl
        f.seek(off + size)
    return None


def _extract_moov_meta(path):
    """Return the bytes of the moov-level `meta` box from a QuickTime/MP4 file, or
    None if there's no moov or no direct `meta` child (e.g. a non-iPhone source)."""
    path = Path(path)
    file_size = path.stat().st_size
    with open(path, "rb") as f:
        moov = _find_top_atom(f, b"moov", file_size)
        if not moov:
            return None
        moov_off, moov_size, moov_hl = moov
        end = moov_off + moov_size
        f.seek(moov_off + moov_hl)
        while f.tell() < end:
            off = f.tell()
            h = _read_atom_header(f)
            if h is None:
                break
            csize, ctyp, _ = h
            if csize <= 0:
                csize = end - off
            if ctyp == b"meta":
                f.seek(off)
                return f.read(csize)
            f.seek(off + csize)
    return None


def copy_apple_metadata(src_path, out_path, fmt):
    """Restore Apple/QuickTime location + camera metadata into a converted MP4/MOV.

    Lifts the source's moov-level `meta` box (GPS, make, model, creationdate) and
    appends it as the output moov's last child so macOS reads it. Best-effort and
    non-destructive: returns True on success, False (no change) for webm, a source
    without moov/meta, or an output whose layout isn't the expected `… mdat, moov`
    (so chunk offsets in stco/co64 can never be invalidated). Any error is swallowed.
    """
    if fmt == "webm":
        return False
    try:
        meta = _extract_moov_meta(src_path)
        if not meta:
            return False
        out_path = Path(out_path)
        out_size = out_path.stat().st_size
        with open(out_path, "r+b") as f:
            moov = _find_top_atom(f, b"moov", out_size)
            mdat = _find_top_atom(f, b"mdat", out_size)
            if not moov:
                return False
            moov_off, moov_size, moov_hl = moov
            # Safe only when moov is the LAST atom and sits after mdat: appending to
            # moov's end == the file's end, and mdat stays put, so every stco/co64
            # chunk offset (which points into the unmoved mdat) remains valid. This
            # is ffmpeg's default (non-faststart) layout; bail otherwise.
            if moov_off + moov_size != out_size:
                return False
            if mdat and mdat[0] > moov_off:
                return False
            new_size = moov_size + len(meta)
            if moov_hl == 8 and new_size > 0xFFFFFFFF:
                return False  # would need a 64-bit size box; moov metadata is tiny
            if moov_hl == 8:
                f.seek(moov_off)
                f.write(struct.pack(">I", new_size))
            else:
                f.seek(moov_off + 8)
                f.write(struct.pack(">Q", new_size))
            f.seek(0, 2)  # append at EOF, which is moov's (new) end
            f.write(meta)
        return True
    except Exception:
        return False


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
    w, _ = target
    w = max(2, w - w % 2)  # floor to nearest even; -2 lets FFmpeg derive height to preserve ratio
    return f"scale={w}:-2:flags=lanczos"


def build_ffmpeg_cmd(input_path, output_path, fmt="mp4", speed=1.0,
                     quality="balanced", resolution="original", dims=None,
                     use_nvenc=False, use_videotoolbox=False, has_audio=None,
                     creation_time=None, codec="h264"):
    """Build the ffmpeg command shared by the web server and the CLI.

    dims: pass (w, h) to skip the ffprobe call (used in tests); otherwise probed.
    has_audio: pass True/False to skip the audio probe; None probes (or assumes
    True when dims is provided, to keep tests ffprobe-free).
    creation_time: explicit ISO-8601 string to embed; None probes the source
    (skipped when dims is provided, to keep tests ffprobe-free).
    codec: 'h264' (default, max compatibility) or 'hevc' (H.265, ~30-50% smaller).
    Ignored for webm output, which always uses VP9.
    """
    if has_audio is None:
        has_audio = True if dims is not None else probe_has_audio(input_path)
    if creation_time is None and dims is None:
        creation_time = probe_creation_time(input_path)
    change_speed = abs(speed - 1.0) > 1e-6

    # Video filters: scale (optional) + speed (only when actually changing speed,
    # so speed=1.0 doesn't force a needless re-encode pass).
    vf_parts = []
    scale = _scale_filter(input_path, resolution, dims)
    if scale:
        vf_parts.append(scale)
    af = None
    if change_speed:
        vf_speed, af = speed_filters(speed)
        vf_parts.append(vf_speed)

    if fmt == "webm":
        cq = CQ_MAP.get(quality, 33)
        vcodec = ["-c:v", "libvpx-vp9", "-crf", str(cq), "-b:v", "0"]
        acodec = ["-c:a", "libopus", "-b:a", "128k"]
    else:
        acodec = ["-c:a", "aac", "-b:a", "128k"]
        is_hevc = codec == "hevc"
        crf_map = HEVC_CRF_MAP if is_hevc else CRF_MAP
        crf_default = 28 if is_hevc else 23
        if use_videotoolbox:
            vq = VQ_MAP.get(quality, 65)
            enc = "hevc_videotoolbox" if is_hevc else "h264_videotoolbox"
            vcodec = ["-c:v", enc, "-q:v", str(vq), "-pix_fmt", "yuv420p"]
        elif use_nvenc:
            crf = crf_map.get(quality, crf_default)
            enc = "hevc_nvenc" if is_hevc else "h264_nvenc"
            vcodec = ["-c:v", enc, "-cq", str(crf), "-preset", "p4", "-pix_fmt", "yuv420p"]
        else:
            crf = crf_map.get(quality, crf_default)
            enc = "libx265" if is_hevc else "libx264"
            vcodec = ["-c:v", enc, "-crf", str(crf), "-preset", "veryfast", "-pix_fmt", "yuv420p"]
        if is_hevc:
            # Apple devices/QuickTime only play HEVC tagged 'hvc1' (FFmpeg defaults to
            # 'hev1', which iPhone/Photos refuse to open).
            vcodec += ["-tag:v", "hvc1"]

    # NOTE: GPS location and other com.apple.quicktime.* keys are NOT preserved by
    # ffmpeg here. -movflags use_metadata_tags only carries them into moov/udta/meta,
    # which macOS Spotlight/Photos ignore — they read the location key from the
    # moov-level meta box. We restore that box verbatim after encoding; see
    # copy_apple_metadata().
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-map_metadata", "0"]
    if creation_time:
        cmd += ["-metadata", f"creation_time={creation_time}"]
    if vf_parts:
        cmd += ["-vf", ",".join(vf_parts)]
    cmd += vcodec
    if has_audio:
        cmd += acodec
        if af:
            cmd += ["-af", af]
    else:
        cmd += ["-an"]  # no audio stream: don't apply audio filters (would error)
    cmd += [str(output_path)]
    return cmd


# ── CLI ──────────────────────────────────────────────────────────────────────

RES_CHOICES = ["original"] + list(RES_BOXES.keys())
FMT_CHOICES = ["mp4", "webm", "mov"]
QUALITY_CHOICES = ["nearlossless", "balanced", "small"]
CODEC_CHOICES = ["h264", "hevc"]


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
    # Codec only applies to mp4/mov; webm is always VP9.
    codec = "h264" if fmt == "webm" else ask_choice("Codec", CODEC_CHOICES, "h264")
    quality = ask_choice("Quality", QUALITY_CHOICES, "balanced")
    resolution = ask_choice("Resolution", RES_CHOICES, "original")
    speed = ask_speed()

    use_nvenc = False
    if fmt != "webm" and has_nvenc():
        use_nvenc = ask_yes_no("NVIDIA NVENC detected. Use GPU encoding?", default=True)

    if fmt == "webm":
        encoder = "libvpx-vp9"
    else:
        gpu = "nvenc" if use_nvenc else None
        encoder = f"{codec}{'_' + gpu if gpu else ''}" if gpu else ("libx265" if codec == "hevc" else "libx264")
    print(f"\nFound {len(files)} video(s). {fmt} @ {resolution}, codec={codec}, quality={quality}, "
          f"speed={speed}x, encoder={encoder}")

    success = 0
    for f in files:
        output_file = build_output_name(f, fmt, speed)
        cmd = build_ffmpeg_cmd(f, output_file, fmt=fmt, speed=speed,
                               quality=quality, resolution=resolution,
                               use_nvenc=use_nvenc, codec=codec)
        print(f"\nConverting: {f.name}")
        print(" ".join(shlex.quote(x) for x in cmd))
        if subprocess.run(cmd).returncode == 0:
            success += 1
            if copy_apple_metadata(f, output_file, fmt):
                print("  (preserved GPS/QuickTime metadata)")
            print(f"Done: {output_file.name}")
        else:
            print(f"Failed: {f.name}")

    print(f"\nFinished. {success}/{len(files)} converted.")


if __name__ == "__main__":
    main()
