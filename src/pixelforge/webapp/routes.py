"""Flask routes.

    GET  /                 -> upload page (format, size, resize-mode,
                                rotate controls; drag-drop upload)
    POST /api/convert      -> accepts multiple uploaded files, runs
                                the batch engine, keeps the output in
                                the ResultStore and returns a JSON
                                manifest: per-file status, a small
                                base64 preview, and a download URL
    GET  /api/batch/<id>/files/<n>
                           -> one converted file from that batch
    GET  /api/batch/<id>/zip
                           -> ZIP of every converted file in that batch,
                                built from stored results (no re-upload,
                                no re-conversion)
    POST /api/convert/zip  -> one-shot: uploads files, returns a ZIP
                                (for scripts; the page uses the GET route)
"""

from __future__ import annotations

import base64
import io
import zipfile

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)

from pixelforge.batch import convert_batch
from pixelforge.core import normalize_format
from pixelforge.webapp.results import ResultStore, StoredFile

bp = Blueprint("main", __name__)

_ALLOWED_RESIZE_MODES = {"fit", "stretch"}

# Output formats that are already compressed: deflating them again in
# the ZIP costs lots of time (hundreds of MB for 8K PNGs) and saves
# almost nothing, so they're stored as-is.
_PRECOMPRESSED_EXTENSIONS = {"jpg", "png", "webp", "avif", "heic", "gif"}

_EXPIRED_MESSAGE = "These results have expired. Please convert again."


def _store() -> ResultStore:
    return current_app.extensions["pixelforge_results"]


def _zip_response(files: list[StoredFile]):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for f in files:
            ext = f.filename.rsplit(".", 1)[-1].lower()
            method = (
                zipfile.ZIP_STORED
                if ext in _PRECOMPRESSED_EXTENSIONS
                else zipfile.ZIP_DEFLATED
            )
            zf.writestr(f.filename, f.data, compress_type=method)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name="pixelforge-converted.zip",
    )


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
    # Unlike the other fields, a bad format is rejected outright (see
    # ValueError handler below): silently converting to something the
    # user didn't pick would be worse than an error.
    target_format = normalize_format(request.form.get("format", "PNG"))

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


@bp.errorhandler(ValueError)
def handle_bad_params(e):
    return jsonify(error=str(e)), 400


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
    summary = convert_batch(files, **params, with_previews=True)

    stored = [StoredFile(r.output_filename, r.data) for r in summary.succeeded]
    batch_id = _store().add(stored)

    results = []
    index = 0
    for r in summary.results:
        entry = {
            "filename": r.filename,
            "status": r.status,
            "message": r.message,
            "output_filename": r.output_filename,
            "size_bytes": len(r.data) if r.data else 0,
        }
        if r.status == "success":
            entry["url"] = url_for(
                "main.batch_file", batch_id=batch_id, index=index
            )
            entry["preview_b64"] = base64.b64encode(r.preview).decode("ascii")
            index += 1
        results.append(entry)

    return jsonify(
        batch_id=batch_id,
        zip_url=url_for("main.batch_zip", batch_id=batch_id) if stored else None,
        results=results,
        counts=summary.counts(),
    )


@bp.route("/api/batch/<batch_id>/files/<int:index>")
def batch_file(batch_id: str, index: int):
    files = _store().get(batch_id)
    if files is None or not 0 <= index < len(files):
        return jsonify(error=_EXPIRED_MESSAGE), 404
    f = files[index]
    return send_file(
        io.BytesIO(f.data),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=f.filename,
    )


@bp.route("/api/batch/<batch_id>/zip")
def batch_zip(batch_id: str):
    files = _store().get(batch_id)
    if not files:
        return jsonify(error=_EXPIRED_MESSAGE), 404
    return _zip_response(files)


@bp.route("/api/convert/zip", methods=["POST"])
def api_convert_zip():
    files = _read_uploaded_files()
    if not files:
        return jsonify(error="No files provided"), 400

    params = _parse_batch_params()
    summary = convert_batch(files, **params)

    if not summary.succeeded:
        return jsonify(error="No files converted successfully"), 400

    return _zip_response(
        [StoredFile(r.output_filename, r.data) for r in summary.succeeded]
    )
