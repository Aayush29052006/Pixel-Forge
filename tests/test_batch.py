"""Tests for pixelforge.batch — folder walking, per-file error
handling, and summary report generation.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from pixelforge.batch import convert_batch


def _make_image_bytes(size=(20, 10), color=(255, 0, 0), fmt="PNG"):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_all_valid_files_succeed():
    files = [
        ("a.png", _make_image_bytes()),
        ("b.png", _make_image_bytes()),
    ]
    summary = convert_batch(files, target_format="jpeg")
    assert summary.counts() == {"success": 2, "skipped": 0, "error": 0}


def test_corrupted_file_is_skipped_not_crashing_batch():
    files = [
        ("good.png", _make_image_bytes()),
        ("bad.png", b"not an image"),
        ("good2.png", _make_image_bytes()),
    ]
    summary = convert_batch(files, target_format="jpeg")
    assert summary.counts() == {"success": 2, "skipped": 0, "error": 1}
    assert summary.errored[0].filename == "bad.png"


def test_unreadable_file_gets_clean_error_message_not_internal_repr():
    """A non-image file should produce a plain, user-facing message —
    not Python's raw exception repr (e.g. a BytesIO object address),
    which used to leak into the UI.
    """
    files = [("bad.jpg", b"this is not an image")]
    summary = convert_batch(files, target_format="jpeg")
    assert summary.errored[0].message == "Not a valid image file"
    assert "0x" not in summary.errored[0].message
    assert "BytesIO" not in summary.errored[0].message


def test_empty_file_is_skipped():
    files = [("empty.png", b"")]
    summary = convert_batch(files, target_format="jpeg")
    assert summary.counts() == {"success": 0, "skipped": 1, "error": 0}


def test_strict_mode_raises_on_first_error_instead_of_recording():
    files = [
        ("good.png", _make_image_bytes()),
        ("bad.png", b"not an image"),
    ]
    with pytest.raises(Exception):
        convert_batch(files, target_format="jpeg", strict=True)


def test_lenient_is_the_default():
    files = [("bad.png", b"not an image")]
    summary = convert_batch(files, target_format="jpeg")
    assert summary.counts()["error"] == 1


def test_empty_batch_returns_empty_summary():
    summary = convert_batch([], target_format="jpeg")
    assert summary.results == []
    assert summary.counts() == {"success": 0, "skipped": 0, "error": 0}


def test_output_filename_uses_jpg_not_jpeg_extension():
    files = [("icon.png", _make_image_bytes())]
    summary = convert_batch(files, target_format="jpeg")
    assert summary.succeeded[0].output_filename == "icon.jpg"


def test_output_filename_collision_gets_deduplicated():
    files = [
        ("icon.png", _make_image_bytes()),
        ("icon.jpeg", _make_image_bytes()),
    ]
    summary = convert_batch(files, target_format="png")
    names = [r.output_filename for r in summary.succeeded]
    assert names == ["icon.png", "icon (1).png"]


def test_converted_bytes_are_actually_valid_in_target_format():
    files = [("icon.png", _make_image_bytes())]
    summary = convert_batch(files, target_format="jpeg")
    result = Image.open(io.BytesIO(summary.succeeded[0].data))
    assert result.format == "JPEG"


def test_resize_and_rotate_params_pass_through():
    files = [("icon.png", _make_image_bytes(size=(100, 50)))]
    summary = convert_batch(
        files, target_format="png", size=(40, 40), resize_mode="fit", rotate=90
    )
    result = Image.open(io.BytesIO(summary.succeeded[0].data))
    assert result.size == (20, 40)
