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
