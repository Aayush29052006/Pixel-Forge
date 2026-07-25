"""Core conversion engine.

Pure image-transformation logic: takes image bytes in, returns image
bytes out. No filesystem I/O, no web framework imports — this module
must stay independently testable and reusable.
"""

from __future__ import annotations

import io
from typing import Literal

from PIL import Image, ImageOps

ResizeMode = Literal["fit", "stretch"]

# Format names Pillow doesn't recognize under their common file extension.
_FORMAT_ALIASES = {
    "JPG": "JPEG",
    "TIF": "TIFF",
}

# Formats that cannot store an alpha channel. Images in these modes must
# be flattened to RGB before saving, or Pillow raises on write.
_NO_ALPHA_FORMATS = {"JPEG", "BMP"}


def convert_image(
    data: bytes,
    *,
    target_format: str,
    size: tuple[int, int] | None = None,
    resize_mode: ResizeMode = "fit",
    rotate: int = 0,
) -> bytes:
    """Convert image bytes to another format, with optional resize/rotate.

    Args:
        data: Raw bytes of the source image.
        target_format: Output format, e.g. "jpeg", "PNG", "webp"
            (case-insensitive; common aliases like "jpg"/"tif" are
            normalized to Pillow's expected names).
        size: Optional (width, height) target size. If None, the image
            is not resized.
        resize_mode: "fit" scales the image (up or down) to fit within
            `size` while preserving aspect ratio. "stretch" forces the
            exact `size`, distorting aspect ratio if needed.
        rotate: Clockwise rotation in degrees. Must be a multiple of 90.

    Returns:
        Bytes of the converted image.

    Raises:
        ValueError: If `rotate` isn't a multiple of 90, `resize_mode`
            is invalid, or `target_format` can't be written by Pillow.
        PIL.UnidentifiedImageError: If `data` isn't a readable image.
    """
    if rotate % 90 != 0:
        raise ValueError(f"rotate must be a multiple of 90, got {rotate}")
    if resize_mode not in ("fit", "stretch"):
        raise ValueError(
            f"resize_mode must be 'fit' or 'stretch', got {resize_mode!r}"
        )

    fmt = target_format.upper()
    fmt = _FORMAT_ALIASES.get(fmt, fmt)

    with Image.open(io.BytesIO(data)) as img:
        img.load()  # force full read now, so corrupt data fails here

        # Normalize any embedded EXIF orientation tag before we apply our
        # own explicit rotation, so the two don't stack.
        img = ImageOps.exif_transpose(img)

        if rotate:
            # PIL's rotate() is counterclockwise for positive angles;
            # negate to get clockwise, matching our documented contract.
            img = img.rotate(-rotate, expand=True)

        if size:
            target_w, target_h = size
            if resize_mode == "stretch":
                img = img.resize((target_w, target_h), Image.LANCZOS)
            else:
                img = _resize_fit(img, target_w, target_h)

        # Palette-mode images (common from GIF/PNG) can trip up encoders
        # for other formats — normalize before any alpha handling.
        if img.mode == "P":
            img = img.convert("RGBA" if "transparency" in img.info else "RGB")

        # Formats without alpha support need a flattened RGB image.
        if fmt in _NO_ALPHA_FORMATS and img.mode in ("RGBA", "LA", "CMYK"):
            img = img.convert("RGB")

        out = io.BytesIO()
        img.save(out, format=fmt)
        return out.getvalue()


def _resize_fit(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Scale `img` to fit within (target_w, target_h), keeping aspect ratio.

    Scales in either direction — shrinks images larger than the target
    box, and enlarges images smaller than it — so the result always
    fills as much of the box as possible on at least one axis without
    exceeding it on either. (Note: enlarging is interpolation, not
    AI upscaling — it won't add real detail to a small source image.)
    """
    src_w, src_h = img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, round(src_w * scale))
    new_h = max(1, round(src_h * scale))
    return img.resize((new_w, new_h), Image.LANCZOS)
