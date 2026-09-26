"""Flask web app package.

create_app() is the application factory: it builds and configures the
Flask app and registers the routes blueprint. Upload-based, since a
browser can't reach into an arbitrary local folder path on the user's
machine — files are sent directly in the request.
"""

from __future__ import annotations

import os

from flask import Flask

from pixelforge.webapp.results import ResultStore

_DEFAULT_MAX_UPLOAD_MB = 300
_DEFAULT_RESULT_CACHE_MB = 2048


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Total request size cap, in MB. This is a local, single-user dev
    # tool, so 300 MB by default is generous — the original 25 MB cap
    # turned out to be too low for real batches of full-resolution
    # photos (a handful of multi-MB JPEGs hits it fast). Overridable
    # via PIXELFORGE_MAX_UPLOAD_MB, mainly so the "upload too large"
    # error path can be tested on demand without editing code, e.g.:
    #   PIXELFORGE_MAX_UPLOAD_MB=1 ./run.sh
    max_upload_mb = int(
        os.environ.get("PIXELFORGE_MAX_UPLOAD_MB", _DEFAULT_MAX_UPLOAD_MB)
    )
    app.config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024

    # Converted batches are kept in memory so downloads and the ZIP
    # don't need a second conversion. Oldest batches are dropped once
    # this budget is passed (the newest one is always kept).
    cache_mb = int(
        os.environ.get("PIXELFORGE_RESULT_CACHE_MB", _DEFAULT_RESULT_CACHE_MB)
    )
    app.extensions["pixelforge_results"] = ResultStore(cache_mb * 1024 * 1024)

    from pixelforge.webapp.routes import bp

    app.register_blueprint(bp)

    return app
