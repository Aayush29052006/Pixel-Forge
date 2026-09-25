"""Tests for pixelforge.webapp — upload route, /api/convert response,
and ZIP download behavior, using Flask's test client.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

from pixelforge.webapp import create_app


def _make_image_bytes(size=(20, 10), color=(255, 0, 0), fmt="PNG"):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Pixel Forge" in resp.data


def test_convert_with_no_files_returns_400(client):
    resp = client.post("/api/convert", data={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_convert_single_file_success(client):
    data = {
        "files": (io.BytesIO(_make_image_bytes()), "icon.png"),
        "format": "JPEG",
    }
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["counts"] == {"success": 1, "skipped": 0, "error": 0}
    assert body["results"][0]["output_filename"] == "icon.jpg"
    assert "data_b64" in body["results"][0]


def test_convert_multiple_files_mixed_results(client):
    data = {
        "files": [
            (io.BytesIO(_make_image_bytes()), "good.png"),
            (io.BytesIO(b"not an image"), "bad.png"),
        ],
        "format": "PNG",
    }
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["counts"] == {"success": 1, "skipped": 0, "error": 1}


def test_convert_applies_resize_params(client):
    data = {
        "files": (io.BytesIO(_make_image_bytes(size=(100, 50))), "icon.png"),
        "format": "PNG",
        "width": "40",
        "height": "40",
        "resize_mode": "fit",
    }
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    body = resp.get_json()
    import base64
    out_bytes = base64.b64decode(body["results"][0]["data_b64"])
    out_img = Image.open(io.BytesIO(out_bytes))
    assert out_img.size == (40, 20)  # 2:1 aspect fit within 40x40


def test_convert_invalid_resize_mode_falls_back_to_fit(client):
    data = {
        "files": (io.BytesIO(_make_image_bytes()), "icon.png"),
        "format": "PNG",
        "resize_mode": "bogus",
    }
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["counts"]["success"] == 1


def test_convert_zip_with_no_files_returns_400(client):
    resp = client.post("/api/convert/zip", data={})
    assert resp.status_code == 400


def test_convert_zip_returns_valid_zip_with_converted_files(client):
    data = {
        "files": [
            (io.BytesIO(_make_image_bytes()), "a.png"),
            (io.BytesIO(_make_image_bytes()), "b.png"),
        ],
        "format": "JPEG",
    }
    resp = client.post("/api/convert/zip", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    names = sorted(zf.namelist())
    assert names == ["a.jpg", "b.jpg"]


def test_convert_zip_excludes_failed_files(client):
    data = {
        "files": [
            (io.BytesIO(_make_image_bytes()), "good.png"),
            (io.BytesIO(b"not an image"), "bad.png"),
        ],
        "format": "PNG",
    }
    resp = client.post("/api/convert/zip", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    assert zf.namelist() == ["good.png"]


def test_convert_zip_all_files_fail_returns_400(client):
    data = {"files": (io.BytesIO(b"not an image"), "bad.png")}
    resp = client.post("/api/convert/zip", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_oversized_upload_returns_json_not_html():
    """A too-large upload must come back as parseable JSON (413), not
    Flask's default HTML error page — otherwise the frontend's
    res.json() call throws and shows a misleading "network error"
    instead of the real "upload too large" message.
    """
    app = create_app()
    app.config["TESTING"] = True
    app.config["MAX_CONTENT_LENGTH"] = 100  # tiny, to trigger 413 cheaply
    with app.test_client() as c:
        data = {"files": (io.BytesIO(_make_image_bytes()), "icon.png")}
        resp = c.post("/api/convert", data=data, content_type="multipart/form-data")
        assert resp.status_code == 413
        assert resp.is_json
        assert "error" in resp.get_json()


def test_max_upload_env_var_is_respected(monkeypatch):
    """PIXELFORGE_MAX_UPLOAD_MB should override the default cap, so the
    413 path can be tested on demand without editing source.
    """
    monkeypatch.setenv("PIXELFORGE_MAX_UPLOAD_MB", "1")
    app = create_app()
    assert app.config["MAX_CONTENT_LENGTH"] == 1 * 1024 * 1024


def test_default_upload_cap_without_env_var(monkeypatch):
    monkeypatch.delenv("PIXELFORGE_MAX_UPLOAD_MB", raising=False)
    app = create_app()
    assert app.config["MAX_CONTENT_LENGTH"] == 300 * 1024 * 1024


def test_convert_unknown_format_returns_400_with_message(client):
    data = {
        "files": (io.BytesIO(_make_image_bytes()), "icon.png"),
        "format": "EXE",
    }
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "Unsupported output format" in resp.get_json()["error"]


def test_convert_heic_upload_to_png(client):
    data = {
        "files": (io.BytesIO(_make_image_bytes(fmt="HEIF")), "IMG_1234.heic"),
        "format": "PNG",
    }
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    body = resp.get_json()
    assert body["counts"]["success"] == 1
    assert body["results"][0]["output_filename"] == "IMG_1234.png"
    assert body["results"][0]["size_bytes"] > 0


def test_no_size_fields_keeps_original_dimensions(client):
    data = {
        "files": (io.BytesIO(_make_image_bytes(size=(123, 45))), "a.png"),
        "format": "WEBP",
    }
    resp = client.post("/api/convert", data=data, content_type="multipart/form-data")
    import base64
    out = base64.b64decode(resp.get_json()["results"][0]["data_b64"])
    assert Image.open(io.BytesIO(out)).size == (123, 45)


def test_index_page_offers_heic_and_lists_it_in_file_picker(client):
    html = client.get("/").get_data(as_text=True)
    assert "<option>HEIC</option>" in html
    assert ".heic" in html
