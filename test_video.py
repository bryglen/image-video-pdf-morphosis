"""Tests for video_convert.convert_video.build_ffmpeg_cmd (dims passed in, so no
ffprobe/ffmpeg needed). Run: python3 test_video.py"""

from video_convert.convert_video import build_ffmpeg_cmd


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


def test_no_audio_uses_an_and_skips_af():
    cmd = " ".join(build_ffmpeg_cmd("in.mp4", "out.mp4", dims=(3840, 2160),
                                    has_audio=False, speed=2.0))
    assert "-an" in cmd
    assert "atempo" not in cmd   # no audio filter applied to a track that doesn't exist
    assert "-c:a" not in cmd
    # video speed filter still applies even with no audio
    assert "setpts=0.500000*PTS" in cmd


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
