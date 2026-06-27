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
