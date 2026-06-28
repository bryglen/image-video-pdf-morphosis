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
                     creation_time=None):
    """Build the ffmpeg command shared by the web server and the CLI.

    dims: pass (w, h) to skip the ffprobe call (used in tests); otherwise probed.
    has_audio: pass True/False to skip the audio probe; None probes (or assumes
    True when dims is provided, to keep tests ffprobe-free).
    creation_time: explicit ISO-8601 string to embed; None probes the source
    (skipped when dims is provided, to keep tests ffprobe-free).
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
        if use_videotoolbox:
            vq = VQ_MAP.get(quality, 65)
            vcodec = ["-c:v", "h264_videotoolbox", "-q:v", str(vq), "-pix_fmt", "yuv420p"]
        elif use_nvenc:
            crf = CRF_MAP.get(quality, 23)
            vcodec = ["-c:v", "h264_nvenc", "-cq", str(crf), "-preset", "p4", "-pix_fmt", "yuv420p"]
        else:
            crf = CRF_MAP.get(quality, 23)
            vcodec = ["-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast", "-pix_fmt", "yuv420p"]

    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-map_metadata", "0"]
    if fmt != "webm":
        # Carry custom QuickTime keys (GPS location, make/model, etc.) into the
        # MP4/MOV output. Without this the mov muxer drops every com.apple.quicktime.*
        # key even with -map_metadata 0. (Not a valid flag for the webm muxer.)
        cmd += ["-movflags", "use_metadata_tags"]
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
    resolution = ask_choice("Resolution", RES_CHOICES, "original")
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
