"""Tests for video_convert.convert_video.build_ffmpeg_cmd (dims passed in, so no
ffprobe/ffmpeg needed). Run: python3 test_video.py"""

import struct
import tempfile
from pathlib import Path

from video_convert.convert_video import (
    build_ffmpeg_cmd, copy_apple_metadata, _extract_moov_meta,
)


def _atom(typ, payload=b""):
    return struct.pack(">I", len(payload) + 8) + typ + payload


# A moov-level meta box (contents are opaque to the surgery — it copies verbatim).
_META = _atom(b"meta", b"\x00\x00\x00\x00" + b"keys-and-ilst-with-ISO6709-here")


def _write(tmp, name, atoms):
    p = Path(tmp) / name
    p.write_bytes(b"".join(atoms))
    return p


def _moov_children(buf):
    """Yield (type, size) of the moov's direct children."""
    i = 0
    while i + 8 <= len(buf):
        size, typ = struct.unpack(">I", buf[i:i + 8][:4])[0], buf[i + 4:i + 8]
        if typ == b"moov":
            inner, end = i + 8, i + size
            while inner + 8 <= end:
                csize = struct.unpack(">I", buf[inner:inner + 4])[0]
                yield buf[inner + 4:inner + 8], csize
                inner += csize
            return
        i += size


def _joined(**kw):
    return " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(3840, 2160), **kw))


def test_scale_filter_added_for_1080p():
    # Height is -2 so ffmpeg derives an even height that preserves the aspect ratio.
    assert "scale=1920:-2:flags=lanczos" in _joined(resolution="1080p")


def test_no_scale_for_original():
    assert "scale=" not in _joined(resolution="original")


def test_no_scale_when_no_upscale():
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(1280, 720), resolution="1080p"))
    assert "scale=" not in cmd


def test_even_dimensions_enforced():
    # 1003x750 @720p → scale=0.96 → width 963; odd → forced down to 962. Height is
    # -2 so ffmpeg derives a matching even height (preserving the ratio).
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(1003, 750), resolution="720p"))
    assert "scale=962:-2:flags=lanczos" in cmd


def test_libx264_default():
    assert "libx264" in _joined(resolution="original")


def test_webm_uses_vp9():
    cmd = _joined(fmt="webm", resolution="original")
    assert "libvpx-vp9" in cmd
    # VP9 constant-quality uses -crf -b:v 0 (NOT -cq, which is an NVENC option).
    assert "-crf 33 -b:v 0" in cmd
    assert "-cq" not in cmd


def test_nvenc_when_requested():
    assert "h264_nvenc" in _joined(fmt="mp4", resolution="original", use_nvenc=True)


def test_quality_maps_to_crf():
    assert "-crf 18" in _joined(fmt="mp4", quality="nearlossless", resolution="original")


def test_hevc_uses_libx265_by_default():
    cmd = _joined(fmt="mp4", codec="hevc", resolution="original")
    assert "libx265" in cmd
    assert "libx264" not in cmd


def test_hevc_adds_hvc1_tag_for_apple_compat():
    assert "-tag:v hvc1" in _joined(fmt="mp4", codec="hevc", resolution="original")


def test_h264_has_no_hvc1_tag():
    assert "hvc1" not in _joined(fmt="mp4", codec="h264", resolution="original")


def test_hevc_crf_map_differs_from_h264():
    assert "-crf 28" in _joined(fmt="mp4", codec="hevc", quality="balanced", resolution="original")
    assert "-crf 22" in _joined(fmt="mp4", codec="hevc", quality="nearlossless", resolution="original")


def test_hevc_videotoolbox_encoder():
    cmd = _joined(fmt="mp4", codec="hevc", resolution="original", use_videotoolbox=True)
    assert "hevc_videotoolbox" in cmd
    assert "-tag:v hvc1" in cmd


def test_hevc_nvenc_encoder():
    assert "hevc_nvenc" in _joined(fmt="mp4", codec="hevc", resolution="original", use_nvenc=True)


def test_webm_ignores_codec():
    # WebM is always VP9 — an HEVC request must not change the encoder or add hvc1.
    cmd = _joined(fmt="webm", codec="hevc", resolution="original")
    assert "libvpx-vp9" in cmd
    assert "hvc1" not in cmd
    assert "libx265" not in cmd


def test_default_resolution_is_original():
    # No resolution arg -> defaults to "original" -> no scale filter (maintain source).
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(3840, 2160)))
    assert "scale=" not in cmd


def test_no_setpts_at_speed_1():
    # speed=1.0 (default) should not add a speed filter — avoids needless re-encode.
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(3840, 2160)))
    assert "setpts" not in cmd
    assert "atempo" not in cmd


def test_no_vf_when_no_scale_and_no_speed():
    # original res + speed 1.0 -> no video filter chain at all.
    cmd = build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(3840, 2160))
    assert "-vf" not in cmd


def test_speed_change_adds_filters():
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(3840, 2160), speed=2.0))
    assert "setpts=0.500000*PTS" in cmd
    assert "-af atempo=2 " in cmd  # trailing zeros stripped by speed_filters


def test_audio_codec_present_with_audio():
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(3840, 2160), has_audio=True))
    assert "-c:a aac" in cmd
    assert "-an" not in cmd


def test_creation_time_explicit_when_provided():
    ts = "2024-03-15T10:30:00.000000Z"
    cmd = build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(1920, 1080), creation_time=ts)
    assert "-metadata" in cmd
    assert f"creation_time={ts}" in cmd


def test_no_use_metadata_tags_movflag():
    # use_metadata_tags only writes Apple's custom keys to moov/udta/meta, which
    # macOS Spotlight/Photos ignore. GPS is restored post-encode by
    # copy_apple_metadata() instead, so the (misleading) flag must NOT be present.
    for fmt in ("mp4", "mov", "webm"):
        cmd = build_ffmpeg_cmd("in.mp4", f"out.{fmt}", dims=(1920, 1080), fmt=fmt)
        assert "use_metadata_tags" not in cmd, f"unexpected use_metadata_tags for {fmt}"


def test_map_metadata_in_all_formats():
    for fmt in ("mp4", "mov", "webm"):
        cmd = build_ffmpeg_cmd("in.mp4", f"out.{fmt}", dims=(1920, 1080), fmt=fmt)
        assert "-map_metadata" in cmd, f"-map_metadata missing for {fmt}"
        assert cmd[cmd.index("-map_metadata") + 1] == "0", f"-map_metadata 0 missing for {fmt}"


def test_no_audio_uses_an_and_skips_af():
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(3840, 2160),
                                    has_audio=False, speed=2.0))
    assert "-an" in cmd
    assert "atempo" not in cmd   # no audio filter applied to a track that doesn't exist
    assert "-c:a" not in cmd
    # video speed filter still applies even with no audio
    assert "setpts=0.500000*PTS" in cmd


def test_copy_apple_metadata_appends_meta_to_moov():
    # source: ftyp + moov[mvhd, meta];  output (ffmpeg layout): ftyp + mdat + moov[mvhd]
    with tempfile.TemporaryDirectory() as tmp:
        src = _write(tmp, "src.mov", [
            _atom(b"ftyp", b"qt  "),
            _atom(b"moov", _atom(b"mvhd", b"\x00" * 100) + _META),
            _atom(b"mdat", b"\x00" * 64),
        ])
        out = _write(tmp, "out.mov", [
            _atom(b"ftyp", b"qt  "),
            _atom(b"mdat", b"\x11" * 200),
            _atom(b"moov", _atom(b"mvhd", b"\x00" * 100)),
        ])
        before = out.stat().st_size
        assert copy_apple_metadata(src, out, "mp4") is True
        buf = out.read_bytes()
        # output grew by exactly the meta box, and moov now contains a meta child
        assert out.stat().st_size == before + len(_META)
        children = list(_moov_children(buf))
        assert (b"meta", len(_META)) in children
        # the moov size field was updated so the container still parses to EOF
        assert buf.endswith(_META)


def test_copy_apple_metadata_noop_for_webm():
    with tempfile.TemporaryDirectory() as tmp:
        src = _write(tmp, "src.mov", [_atom(b"moov", _META)])
        out = _write(tmp, "out.webm", [_atom(b"moov", b"\x00" * 32)])
        before = out.read_bytes()
        assert copy_apple_metadata(src, out, "webm") is False
        assert out.read_bytes() == before  # untouched


def test_copy_apple_metadata_noop_without_source_meta():
    # A non-iPhone source with no moov/meta -> nothing to copy, output untouched.
    with tempfile.TemporaryDirectory() as tmp:
        src = _write(tmp, "src.mov", [_atom(b"moov", _atom(b"mvhd", b"\x00" * 50))])
        out = _write(tmp, "out.mov", [
            _atom(b"mdat", b"\x11" * 100),
            _atom(b"moov", _atom(b"mvhd", b"\x00" * 50)),
        ])
        before = out.read_bytes()
        assert copy_apple_metadata(src, out, "mp4") is False
        assert out.read_bytes() == before


def test_copy_apple_metadata_bails_when_moov_not_last():
    # If something follows moov (moov not the last atom), appending is unsafe -> bail.
    with tempfile.TemporaryDirectory() as tmp:
        src = _write(tmp, "src.mov", [_atom(b"moov", _META)])
        out = _write(tmp, "out.mov", [
            _atom(b"moov", _atom(b"mvhd", b"\x00" * 50)),  # moov BEFORE mdat
            _atom(b"mdat", b"\x11" * 100),
        ])
        before = out.read_bytes()
        assert copy_apple_metadata(src, out, "mp4") is False
        assert out.read_bytes() == before


def test_extract_moov_meta_returns_box_verbatim():
    with tempfile.TemporaryDirectory() as tmp:
        src = _write(tmp, "src.mov", [
            _atom(b"ftyp", b"qt  "),
            _atom(b"moov", _atom(b"mvhd", b"\x00" * 40) + _META),
        ])
        assert _extract_moov_meta(src) == _META


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
