# Resolution Downscaling + Converter Consolidation — Design

**Date:** 2026-06-23
**Component:** Media Converter (web app + CLI tools)

## Goals

1. **Resolution downscaling.** Let the user downscale media to a chosen preset
   (e.g. 4K → 1080p) to save phone storage — keeping aspect ratio, never
   upscaling. Available in both the web UI and the CLI tools, for image + video.
2. **Consolidate converters.** Remove the duplicated logic so each media type has
   ONE module shared by both the web server and the CLI. Image and video stay as
   separate modules.

## Current state (the problem)

- **Image:** `image_convert/converter.py` (logic) + `image_convert/image_converter.py`
  (CLI that imports the logic). Clean split, but two files.
- **Video:** logic is **duplicated and drifted** —
  - `server.py` inline: MP4/WebM/MOV, quality CRF/CQ maps, live progress, `scale=-2:1080`.
  - `video_convert/convert_video.py`: MP4 only, optional NVENC, fixed CRF 18, `scale=-2:1080`.
- Resolution is hardcoded to 1080p for video and not applied at all for images.

## Resolution semantics (Approach A — orientation-aware bounding box)

Each preset is a **long × short** bounding box. Media is scaled to fit inside the
box (long side along the box's long side), preserving aspect ratio. Downscale
only — if the source already fits, leave it untouched.

| Preset    | Box (long × short) |
|-----------|--------------------|
| Original  | no resize          |
| 4K (2160p)| 3840 × 2160        |
| 1440p     | 2560 × 1440        |
| 1080p     | 1920 × 1080        |
| 720p      | 1280 × 720         |
| 480p      | 854 × 480          |

Examples: landscape 4K @1080p → 1920×1080; portrait 4K @1080p → 1080×1920;
720p source @1080p → unchanged (no upscale).

**Defaults:** Image → Original (downscale is opt-in). Video → Original
(per user decision: maintain source resolution by default; downscaling is opt-in).

## Target structure

```
tools/
├── server.py                       # thin Flask routes — imports both converters
├── resolution.py                   # NEW shared: RES_BOXES + compute_target_size (pure)
├── image_convert/
│   └── image_converter.py          # image logic + CLI main() (absorbs converter.py)
└── video_convert/
    └── convert_video.py            # video logic + CLI main() (absorbs server's video logic)
```

`image_convert/converter.py` is **removed** (folded into `image_converter.py`).
Stale packaging (`image_convert/pyproject.toml`, `build/`, `*.egg-info`) left as-is.

## Module responsibilities

### `resolution.py` (new, shared)

```python
RES_BOXES = {
    "2160p": (3840, 2160), "1440p": (2560, 1440), "1080p": (1920, 1080),
    "720p":  (1280, 720),  "480p":  (854, 480),
}

def compute_target_size(w, h, preset):
    """Fit (w,h) inside the preset box, preserving aspect ratio, never upscaling.
    Return (new_w, new_h), or None for 'original'/unknown/already-fits (no-op)."""
```

Orientation-aware (swaps box dims when `h > w`), clamps scale ≤ 1.0. Single
source of truth for the presets, imported by both converters.

### `image_convert/image_converter.py` (combined logic + CLI)

- Absorbs everything from `converter.py`: `INPUT_EXTS`, `OUTPUT_FORMATS`,
  `MIME_TYPES`, `flatten_alpha_to_white`, `normalize_mode`, `convert_image`.
- `convert_image(img, out_fmt, lossless=True, resolution="original")` —
  computes target from `img.width/height` via `compute_target_size` and, if not
  None, `img = img.resize(target, Image.LANCZOS)` (high-quality downscale) before
  encoding. EXIF/ICC passthrough unchanged.
- `main()` CLI (from old `image_converter.py`): existing format + lossless
  prompts, **plus a resolution prompt**. Already at feature parity with the web.

### `video_convert/convert_video.py` (combined logic + CLI)

- `VIDEO_EXTS`, `VIDEO_MIME`, `CRF_MAP`, `CQ_MAP`.
- `speed_filters(speed) -> (vf, af)` (the chained-atempo logic, deduped).
- `probe_dimensions(path) -> (w, h) | None` via `ffprobe`.
- `has_ffmpeg()`, `has_nvenc()` (from the old CLI).
- `build_ffmpeg_cmd(input, output, fmt="mp4", speed=1.0, quality="balanced",
  resolution="1080p", dims=None, use_nvenc=False) -> list[str]` — the single
  command builder both front-ends use:
  - dims defaulted via `probe_dimensions`; `compute_target_size` → optional
    `scale=W:H:flags=lanczos` (W,H forced even); else no scale filter.
  - codec: WebM → libvpx-vp9 (`-crf <CQ_MAP> -b:v 0`; VP9 constant-quality, NOT
    `-cq` which is NVENC-only); else h264 — `h264_nvenc` if `use_nvenc`,
    otherwise `libx264` (`-crf`). NVENC ignored for WebM.
- `main()` CLI: prompts for **format + quality + speed + resolution** (full
  parity with web) plus NVENC auto-detect; batch over a file/folder.

### `server.py` (thin)

- Imports: `from image_convert.image_converter import convert_image,
  OUTPUT_FORMATS, MIME_TYPES`; `from video_convert.convert_video import
  build_ffmpeg_cmd, VIDEO_MIME`.
- Image route: read `resolution` form field → `convert_image(..., resolution=…)`.
- Video job: read `resolution` → `build_ffmpeg_cmd(..., use_nvenc=False)` → run
  with the existing Popen/stderr progress parsing. Drops the inline
  `_speed_filters`, CRF/CQ maps, and hardcoded scale.

**Imports resolve** because `server.py` runs from `tools/` (per `start.sh`):
`image_convert`/`video_convert` are implicit namespace packages and `resolution`
is a sibling. Each CLI adds the repo root to `sys.path` (same one-liner pattern
`server.py` uses today) so it also works run from its own folder.

## UI — `index.html`

Add one `Resolution` `.options-row` per tab, mirroring the existing `.fmt-btn` /
`makeOptionPicker` pattern (no new CSS):

```html
<div class="options-row">
  <span class="option-label">Resolution</span>
  <div class="fmt-group" id="imgResGroup">   <!-- vidResGroup for video -->
    <button class="fmt-btn active" data-res="original">Original</button>
    <button class="fmt-btn" data-res="2160p">4K</button>
    <button class="fmt-btn" data-res="1440p">1440p</button>
    <button class="fmt-btn" data-res="1080p">1080p</button>
    <button class="fmt-btn" data-res="720p">720p</button>
    <button class="fmt-btn" data-res="480p">480p</button>
  </div>
</div>
```

- Image group default active: `original`. Video group default active: `original`.
- JS: `let imgRes='original'` / `let vidRes='1080p'`, wire with
  `makeOptionPicker`, and `form.append('resolution', …)` in both convert calls.

## Data flow

```
UI / CLI resolution choice → "resolution" preset string
  image: convert_image → compute_target_size → img.resize(LANCZOS) → encode
  video: build_ffmpeg_cmd → probe_dimensions → compute_target_size → scale filter
```

## Error handling

- `ffprobe` missing / unparseable → `probe_dimensions` returns None → video
  converts at original resolution (no crash).
- Unknown/`original` preset → `compute_target_size` returns None → no resize.

## Testing

- **Unit:** `test_resolution.py` covers `compute_target_size` —
  landscape/portrait/square sources, each preset, no-upscale clamp,
  `original`/unknown → None. (Even-dimension forcing lives in the video command
  builder, verified in the manual video check.)
- **Manual:** run the server; convert a known 4K image and 4K video at a couple
  of presets; confirm output dimensions + size reduction. Run each CLI once to
  confirm prompts + output.

## Migration / cleanup

- Delete `image_convert/converter.py` after folding into `image_converter.py`.
- Update `README.md`: new CLI invocations, resolution options, note both web +
  CLI share one module per media type.

## Out of scope

- Stale packaging files in `image_convert/` (pyproject/build/egg-info).
- No git commit of this doc — `tools/` is not a git repository.
