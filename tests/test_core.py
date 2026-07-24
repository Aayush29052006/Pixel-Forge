"""Tests for pixelforge.core.

Uses Pillow itself to generate small synthetic test images in-memory
rather than depending on committed fixture files — keeps tests fast
and self-contained.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from pixelforge.core import convert_image


def _make_image_bytes(mode="RGB", size=(20, 10), color=(255, 0, 0), fmt="PNG"):
    img = Image.new(mode, size, color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_format_conversion_png_to_jpeg():
    data = _make_image_bytes()
    out = convert_image(data, target_format="JPEG")
    result = Image.open(io.BytesIO(out))
    assert result.format == "JPEG"


def test_format_conversion_preserves_pixel_content():
    data = _make_image_bytes(color=(10, 20, 30))
    out = convert_image(data, target_format="PNG")
    result = Image.open(io.BytesIO(out))
    assert result.getpixel((0, 0)) == (10, 20, 30)


def test_jpg_alias_normalizes_to_jpeg():
    data = _make_image_bytes()
    out = convert_image(data, target_format="jpg")
    result = Image.open(io.BytesIO(out))
    assert result.format == "JPEG"


def test_resize_stretch_hits_exact_dimensions():
    data = _make_image_bytes(size=(100, 50))
    out = convert_image(data, target_format="PNG", size=(40, 40), resize_mode="stretch")
    result = Image.open(io.BytesIO(out))
    assert result.size == (40, 40)


def test_resize_fit_preserves_aspect_ratio():
    data = _make_image_bytes(size=(100, 50))  # 2:1 aspect ratio
    out = convert_image(data, target_format="PNG", size=(40, 40), resize_mode="fit")
    result = Image.open(io.BytesIO(out))
    assert result.size == (40, 20)  # fits within 40x40, keeps 2:1 ratio


def test_rotate_90_clockwise_swaps_dimensions():
    data = _make_image_bytes(size=(100, 50))
    out = convert_image(data, target_format="PNG", rotate=90)
    result = Image.open(io.BytesIO(out))
    assert result.size == (50, 100)


def test_rotate_270_is_equivalent_to_90_counterclockwise():
    data = _make_image_bytes(size=(100, 50))
    out = convert_image(data, target_format="PNG", rotate=270)
    result = Image.open(io.BytesIO(out))
    assert result.size == (50, 100)


def test_rotate_invalid_degree_raises():
    data = _make_image_bytes()
    with pytest.raises(ValueError):
        convert_image(data, target_format="PNG", rotate=45)


def test_invalid_resize_mode_raises():
    data = _make_image_bytes()
    with pytest.raises(ValueError):
        convert_image(data, target_format="PNG", size=(10, 10), resize_mode="bogus")


def test_rgba_to_jpeg_strips_alpha_without_crashing():
    data = _make_image_bytes(mode="RGBA", color=(255, 0, 0, 128))
    out = convert_image(data, target_format="JPEG")
    result = Image.open(io.BytesIO(out))
    assert result.mode == "RGB"


def test_palette_mode_gif_converts_cleanly():
    data = _make_image_bytes(mode="P", size=(10, 10), color=0, fmt="GIF")
    out = convert_image(data, target_format="PNG")
    result = Image.open(io.BytesIO(out))
    assert result.format == "PNG"


def test_corrupted_data_raises():
    with pytest.raises(Exception):
        convert_image(b"not an image", target_format="PNG")


def test_no_resize_when_size_omitted():
    data = _make_image_bytes(size=(33, 17))
    out = convert_image(data, target_format="PNG")
    result = Image.open(io.BytesIO(out))
    assert result.size == (33, 17)
