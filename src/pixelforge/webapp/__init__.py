"""Flask web app package.

create_app() is the application factory: it builds and configures the
Flask app and registers the routes blueprint. Upload-based, since a
browser can't reach into an arbitrary local folder path on the user's
machine — files are sent directly in the request.
"""

from __future__ import annotations

from flask import Flask


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Generous cap for "hundreds of icon-sized images" while still
    # bounding memory use from a runaway or malicious upload.
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB

    from pixelforge.webapp.routes import bp

    app.register_blueprint(bp)

    return app
