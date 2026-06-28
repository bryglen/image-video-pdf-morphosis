import io, sys, re, uuid, shutil, threading, subprocess, tempfile, zipfile, base64
from pathlib import Path
from flask import Flask, request, send_file, jsonify

sys.path.insert(0, str(Path(__file__).resolve().parent))
from image_convert.image_converter import convert_image, OUTPUT_FORMATS, MIME_TYPES
from video_convert.convert_video import (
    build_ffmpeg_cmd, VIDEO_MIME, has_videotoolbox, has_hevc_videotoolbox,
    has_hevc_encoder, probe_metadata, copy_apple_metadata,
)
from pdf_convert.pdf_converter import (
    images_to_pdf, pdf_to_images,
    parse_page_ranges, pdf_page_count, pdf_thumbnails, extract_pdf_pages,
    extract_pdf_pages_batch,
    compress_pdf,
)
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()

app = Flask(__name__, static_folder=".")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024 * 1024  # 5 GB

_USE_VIDEOTOOLBOX = has_videotoolbox()
_USE_HEVC_VIDEOTOOLBOX = has_hevc_videotoolbox()
_HAS_HEVC = has_hevc_encoder()

# All converter temp dirs live in a project-local tmp/ folder so cleanup is
# unambiguous and self-contained (not scattered across the system temp dir).
TEMP_BASE = Path(__file__).resolve().parent / "tmp"


def _sweep_temp_base():
    """Remove leftover job dirs (missed downloads, crashes) on startup.

    Safe: only touches our own namespace dir, never the shared $TMPDIR root.
    """
    if not TEMP_BASE.exists():
        return
    for child in TEMP_BASE.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)


TEMP_BASE.mkdir(parents=True, exist_ok=True)
_sweep_temp_base()

_jobs: dict = {}
_jobs_lock = threading.Lock()


@app.route("/")
def index():
    return send_file("index.html")


# ── Image ──────────────────────────────────────────────────────────────────

@app.route("/api/image/convert", methods=["POST"])
def image_convert():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400

    file = request.files["file"]
    out_fmt = request.form.get("format", "jpg").lower()
    lossless = request.form.get("lossless", "true").lower() != "false"
    resolution = request.form.get("resolution", "original").lower()

    if out_fmt not in OUTPUT_FORMATS:
        return jsonify(error=f"Unsupported format: {out_fmt}"), 400

    try:
        raw = file.read()
        before_size = len(raw)
        img = Image.open(io.BytesIO(raw))
        img.load()
        data = convert_image(img, out_fmt, lossless=lossless, resolution=resolution)
        after_size = len(data)

        ext = ".jpg" if out_fmt == "jpeg" else f".{out_fmt}"
        stem = Path(file.filename).stem if file.filename else "converted"
        response = send_file(
            io.BytesIO(data),
            mimetype=MIME_TYPES.get(out_fmt, "application/octet-stream"),
            as_attachment=True,
            download_name=f"{stem}_converted{ext}",
        )
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["Access-Control-Expose-Headers"] = "X-Before-Size, X-After-Size"
        return response
    except Exception as e:
        return jsonify(error=str(e)), 500


# ── Video ──────────────────────────────────────────────────────────────────

def _parse_duration(line: str):
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", line)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def _parse_time(line: str):
    m = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", line)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def _run_video_job(job_id, input_path, output_path, out_fmt, speed, quality, resolution, codec):
    # HEVC and H.264 have separate VideoToolbox encoders; pick the one that exists.
    use_vt = _USE_HEVC_VIDEOTOOLBOX if codec == "hevc" else _USE_VIDEOTOOLBOX
    cmd = build_ffmpeg_cmd(input_path, output_path, fmt=out_fmt, speed=speed,
                           quality=quality, resolution=resolution,
                           use_videotoolbox=use_vt, codec=codec)
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True)

    # Register the process so /cancel can terminate it. If the job was cancelled
    # before we got here, the entry is already gone — kill and bail.
    with _jobs_lock:
        if job_id not in _jobs:
            proc.terminate()
            return
        _jobs[job_id]["proc"] = proc

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
        job = _jobs.get(job_id)
        if job is None or job.get("cancelled"):
            return  # cancel route owns cleanup
        if proc.returncode == 0:
            # FFmpeg drops the iPhone GPS/QuickTime metadata that macOS reads;
            # restore it before reporting the (slightly larger) output size.
            copy_apple_metadata(input_path, output_path, out_fmt)
            job.update(status="done", progress=100, after_size=output_path.stat().st_size)
        else:
            job.update(status="error", error="FFmpeg conversion failed")


@app.route("/api/video/probe", methods=["POST"])
def video_probe():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400
    file = request.files["file"]
    tmpdir = tempfile.mkdtemp(dir=TEMP_BASE)
    try:
        fname = Path(file.filename).name if file.filename else "video.mp4"
        path = Path(tmpdir) / fname
        file.save(str(path))
        return jsonify(probe_metadata(path))
    except Exception as e:
        return jsonify(error=str(e)), 500
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.route("/api/video/convert", methods=["POST"])
def video_convert():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400

    file    = request.files["file"]
    out_fmt = request.form.get("format", "mp4").lower()
    speed   = float(request.form.get("speed", "1.0"))
    quality = request.form.get("quality", "balanced")
    resolution = request.form.get("resolution", "original").lower()
    codec   = request.form.get("codec", "h264").lower()
    if codec not in ("h264", "hevc"):
        codec = "h264"
    if codec == "hevc" and out_fmt != "webm" and not _HAS_HEVC:
        return jsonify(error="HEVC not supported by this FFmpeg build. "
                             "Install libx265 (e.g. brew install ffmpeg) or use H.264."), 400

    tmpdir      = tempfile.mkdtemp(dir=TEMP_BASE)
    fname       = Path(file.filename).name if file.filename else "video.mp4"
    input_path  = Path(tmpdir) / fname
    output_path = Path(tmpdir) / f"{Path(fname).stem}_converted.{out_fmt}"

    file.save(str(input_path))
    before_size = input_path.stat().st_size
    job_id = str(uuid.uuid4())

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running", "progress": 0,
            "output_path": output_path, "tmpdir": tmpdir,
            "before_size": before_size, "after_size": None,
            "stem": Path(fname).stem, "out_fmt": out_fmt,
            "error": None, "proc": None, "cancelled": False,
        }

    threading.Thread(
        target=_run_video_job,
        args=(job_id, input_path, output_path, out_fmt, speed, quality, resolution, codec),
        daemon=True,
    ).start()

    return jsonify(job_id=job_id, before_size=before_size)


@app.route("/api/video/status/<job_id>")
def video_status(job_id):
    with _jobs_lock:
        job = dict(_jobs.get(job_id, {}))
    if not job:
        return jsonify(error="Job not found"), 404
    return jsonify(
        status=job["status"], progress=job["progress"],
        error=job.get("error"), before_size=job["before_size"],
        after_size=job.get("after_size"),
    )


@app.route("/api/video/cancel/<job_id>", methods=["POST"])
def video_cancel(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify(error="Job not found"), 404
        job["cancelled"] = True
        proc = job.get("proc")
        tmpdir = job.get("tmpdir")

    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)
    with _jobs_lock:
        _jobs.pop(job_id, None)
    return jsonify(status="cancelled")


@app.route("/api/video/download/<job_id>")
def video_download(job_id):
    with _jobs_lock:
        job = dict(_jobs.get(job_id, {}))
    if not job or job["status"] != "done":
        return jsonify(error="Not ready"), 404

    tmpdir      = job["tmpdir"]
    output_path = job["output_path"]
    out_fmt     = job["out_fmt"]
    stem        = job["stem"]

    def _deferred_cleanup():
        import time; time.sleep(60)
        shutil.rmtree(tmpdir, ignore_errors=True)
        with _jobs_lock: _jobs.pop(job_id, None)

    threading.Thread(target=_deferred_cleanup, daemon=True).start()

    download_name = request.args.get("filename") or f"{stem}_converted.{out_fmt}"
    return send_file(
        output_path,
        mimetype=VIDEO_MIME.get(out_fmt, "video/mp4"),
        as_attachment=True,
        download_name=download_name,
    )


# ── PDF ──────────────────────────────────────────────────────────────────────

@app.route("/api/pdf/from-images", methods=["POST"])
def pdf_from_images():
    files = request.files.getlist("file")
    if not files:
        return jsonify(error="No file provided"), 400

    try:
        before_size = 0
        images = []
        for f in files:
            raw = f.read()
            before_size += len(raw)
            im = Image.open(io.BytesIO(raw))
            im.load()
            images.append(im)

        data = images_to_pdf(images)
        after_size = len(data)

        if len(files) > 1:
            download_name = "combined.pdf"
        else:
            stem = Path(files[0].filename).stem if files[0].filename else "converted"
            download_name = f"{stem}_converted.pdf"

        response = send_file(
            io.BytesIO(data), mimetype="application/pdf",
            as_attachment=True, download_name=download_name,
        )
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["Access-Control-Expose-Headers"] = "X-Before-Size, X-After-Size"
        return response
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/pdf/to-images", methods=["POST"])
def pdf_to_images_route():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400

    file = request.files["file"]
    out_fmt = request.form.get("format", "png").lower()
    try:
        dpi = int(request.form.get("dpi", "150"))
    except ValueError:
        dpi = 150
    if dpi <= 0:
        dpi = 150

    try:
        raw = file.read()
        before_size = len(raw)
        results = pdf_to_images(raw, fmt=out_fmt, dpi=dpi)
        if not results:
            return jsonify(error="PDF has no pages"), 500

        stem = Path(file.filename).stem if file.filename else "pdf"

        if len(results) == 1:
            name, data = results[0]
            ext = name.rsplit(".", 1)[-1]
            mime = "image/jpeg" if ext == "jpg" else "image/png"
            payload, after_size = io.BytesIO(data), len(data)
            download_name = f"{stem}_{name}"
        else:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in results:
                    zf.writestr(name, data)
            after_size = payload.tell()
            payload.seek(0)
            mime = "application/zip"
            download_name = f"{stem}_pages.zip"

        response = send_file(payload, mimetype=mime, as_attachment=True,
                             download_name=download_name)
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["Access-Control-Expose-Headers"] = "X-Before-Size, X-After-Size"
        return response
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/pdf/thumbnails", methods=["POST"])
def pdf_thumbnails_route():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400
    file = request.files["file"]
    try:
        raw = file.read()
        thumbs = pdf_thumbnails(raw)
        if not thumbs:
            return jsonify(error="PDF has no pages"), 500
        return jsonify(
            page_count=len(thumbs),
            thumbnails=[
                {"page": n,
                 "dataUrl": "data:image/png;base64," + base64.b64encode(b).decode("ascii")}
                for n, b in thumbs
            ],
        )
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/pdf/extract", methods=["POST"])
def pdf_extract_route():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400
    file = request.files["file"]
    pages_text = request.form.get("pages", "")
    combine = request.form.get("combine", "true").lower() != "false"

    try:
        raw = file.read()
        before_size = len(raw)
        pages = parse_page_ranges(pages_text, pdf_page_count(raw))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=str(e)), 500

    try:
        results = extract_pdf_pages(raw, pages, combine=combine)
        stem = Path(file.filename).stem if file.filename else "pdf"

        if len(results) == 1:
            name, data = results[0]
            payload, after_size = io.BytesIO(data), len(data)
            mime = "application/pdf"
            download_name = f"{stem}_{name}"
        else:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in results:
                    zf.writestr(name, data)
            after_size = payload.tell()
            payload.seek(0)
            mime = "application/zip"
            download_name = f"{stem}_pages.zip"

        response = send_file(payload, mimetype=mime, as_attachment=True,
                             download_name=download_name)
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["Access-Control-Expose-Headers"] = "X-Before-Size, X-After-Size"
        return response
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/pdf/extract-batch", methods=["POST"])
def pdf_extract_batch_route():
    files = request.files.getlist("file")
    page_specs = request.form.getlist("pages")
    if not files:
        return jsonify(error="No file provided"), 400
    if len(page_specs) != len(files):
        return jsonify(error="Mismatched files and page ranges"), 400
    combine = request.form.get("combine", "true").lower() != "false"

    items = []
    before_size = 0
    for f, spec in zip(files, page_specs):
        raw = f.read()
        before_size += len(raw)
        try:
            pages = parse_page_ranges(spec, pdf_page_count(raw))
        except ValueError as e:
            return jsonify(error=f"{f.filename or 'PDF'}: {e}"), 400
        except Exception as e:
            return jsonify(error=str(e)), 500
        items.append((f.filename or "pdf", raw, pages))

    try:
        results = extract_pdf_pages_batch(items, combine=combine)
        if not results:
            return jsonify(error="No pages selected"), 400
        if len(results) == 1:
            name, data = results[0]
            payload, after_size = io.BytesIO(data), len(data)
            mime, download_name = "application/pdf", name
        else:
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
                for name, data in results:
                    zf.writestr(name, data)
            after_size = payload.tell()
            payload.seek(0)
            mime, download_name = "application/zip", "pages.zip"

        response = send_file(payload, mimetype=mime, as_attachment=True,
                             download_name=download_name)
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["Access-Control-Expose-Headers"] = "X-Before-Size, X-After-Size"
        return response
    except Exception as e:
        return jsonify(error=str(e)), 500


@app.route("/api/pdf/compress", methods=["POST"])
def pdf_compress_route():
    if "file" not in request.files:
        return jsonify(error="No file provided"), 400
    file = request.files["file"]
    quality = request.form.get("quality", "balanced").lower()

    target_bytes = None
    try:
        target_mb = float(request.form.get("target_mb", ""))
        if target_mb > 0:
            target_bytes = int(target_mb * 1024 * 1024)
    except (TypeError, ValueError):
        target_bytes = None

    try:
        raw = file.read()
        before_size = len(raw)
        data, engine = compress_pdf(raw, quality=quality, target_bytes=target_bytes)
        after_size = len(data)
        stem = Path(file.filename).stem if file.filename else "pdf"
        response = send_file(
            io.BytesIO(data), mimetype="application/pdf",
            as_attachment=True, download_name=f"{stem}_compressed.pdf",
        )
        response.headers["X-Before-Size"] = str(before_size)
        response.headers["X-After-Size"] = str(after_size)
        response.headers["X-Compress-Engine"] = engine
        response.headers["Access-Control-Expose-Headers"] = \
            "X-Before-Size, X-After-Size, X-Compress-Engine"
        return response
    except Exception as e:
        return jsonify(error=str(e)), 500


if __name__ == "__main__":
    app.run(debug=False, port=5002, threaded=True)
