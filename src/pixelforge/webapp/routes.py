"""Flask routes.

    GET  /                 -> upload page (format, size, resize-mode,
                                rotate controls; drag-drop upload)
    POST /api/convert      -> accepts multiple uploaded files, runs
                                the batch engine, returns a JSON
                                manifest (per-file status + base64
                                data for successes) that the page uses
                                to render the results panel and offer
                                individual downloads
    POST /api/convert/zip  -> same input, returns a ZIP archive of
                                every successfully converted file
"""

from __future__ import annotations

import base64
import io
import zipfile

from flask import Blueprint, jsonify, render_template, request, send_file

from pixelforge.batch import convert_batch

bp = Blueprint("main", __name__)

_ALLOWED_RESIZE_MODES = {"fit", "stretch"}


def _read_uploaded_files() -> list[tuple[str, bytes]]:
    """Pull (filename, bytes) pairs out of the current request's files."""
    uploads = request.files.getlist("files")
    return [(f.filename or "unnamed", f.read()) for f in uploads]


def _parse_batch_params() -> dict:
    """Parse and validate the form fields shared by both convert routes.

    Falls back to safe defaults for anything missing or malformed
    rather than erroring — the batch engine itself is what enforces
    real validation (e.g. rotate must be a multiple of 90).
    """
    target_format = request.form.get("format", "PNG")

    width = request.form.get("width", type=int)
    height = request.form.get("height", type=int)
    size = (width, height) if width and height else None

    resize_mode = request.form.get("resize_mode", "fit")
    if resize_mode not in _ALLOWED_RESIZE_MODES:
        resize_mode = "fit"

    rotate = request.form.get("rotate", default=0, type=int) or 0

    return {
        "target_format": target_format,
        "size": size,
        "resize_mode": resize_mode,
        "rotate": rotate,
    }


@bp.app_errorhandler(413)
def handle_payload_too_large(e):
    return jsonify(
        error="Upload too large. Try converting fewer files at once, "
        "or a smaller batch."
    ), 413


@bp.app_errorhandler(500)
def handle_server_error(e):
    return jsonify(error="Something went wrong on the server."), 500


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/api/convert", methods=["POST"])
def api_convert():
    files = _read_uploaded_files()
    if not files:
        return jsonify(error="No files provided"), 400

    params = _parse_batch_params()
    summary = convert_batch(files, **params)

    results = []
    for r in summary.results:
        entry = {
            "filename": r.filename,
            "status": r.status,
            "message": r.message,
            "output_filename": r.output_filename,
        }
        if r.status == "success" and r.data:
            entry["data_b64"] = base64.b64encode(r.data).decode("ascii")
        results.append(entry)

    return jsonify(results=results, counts=summary.counts())


@bp.route("/api/convert/zip", methods=["POST"])
def api_convert_zip():
    files = _read_uploaded_files()
    if not files:
        return jsonify(error="No files provided"), 400

    params = _parse_batch_params()
    summary = convert_batch(files, **params)

    if not summary.succeeded:
        return jsonify(error="No files converted successfully"), 400

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in summary.succeeded:
            zf.writestr(r.output_filename, r.data)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="pixelforge-converted.zip",
    )
