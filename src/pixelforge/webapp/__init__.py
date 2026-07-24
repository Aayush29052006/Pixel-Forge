"""Flask web app package.

Planned: create_app() factory function that registers routes.py and
returns a configured Flask app. Uses core.convert_image() / the batch
runner — upload-based, since a browser can't point at an arbitrary
local folder path on the server.
"""
