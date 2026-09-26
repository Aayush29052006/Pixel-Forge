"""Core conversion engine.

Pure image-transformation logic: takes image bytes in, returns image
bytes out. No filesystem I/O, no web framework imports — this module
must stay independently testable and reusable.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

import pillow_heif
from PIL import Image, ImageOps, ImageSequence

ResizeMode = Literal["fit", "stretch"]

# Teach Pillow to read and write HEIC/HEIF (iPhone photos). AVIF is
# supported natively by Pillow 11.3+, so no extra plugin is needed.
pillow_heif.register_heif_opener()

# Pillow refuses images over 2x this many pixels as a "decompression
# bomb". The default (~89 MP, so a hard stop at ~179 MP) rejects real
# photos from 200 MP phone cameras; this raises the hard stop to
# ~256 MP while still protecting against absurd inputs.
Image.MAX_IMAGE_PIXELS = 128_000_000

# Largest width/height a caller may request. Big enough for every
# preset (8K tops out at 8192), small enough to not exhaust memory.
MAX_DIMENSION = 16384

# Upper bound on total pixels across all frames of an animation, so a
# long GIF resized to 8K can't eat all available memory.
_MAX_ANIMATION_PIXELS = 500_000_000


@dataclass(frozen=True)
class _OutputFormat:
    pillow_name: str  # name Pillow's save() expects
    extension: str  # file extension for converted files
    supports_alpha: bool
    supports_animation: bool = False


# Every output format the app offers, keyed by the name users pick.
_OUTPUT_FORMATS = {
    "JPEG": _OutputFormat("JPEG", "jpg", supports_alpha=False),
    "PNG": _OutputFormat("PNG", "png", True, supports_animation=True),
    "WEBP": _OutputFormat("WEBP", "webp", True, supports_animation=True),
    "AVIF": _OutputFormat("AVIF", "avif", True),
    "HEIC": _OutputFormat("HEIF", "heic", True),
    "GIF": _OutputFormat("GIF", "gif", True, supports_animation=True),
    "BMP": _OutputFormat("BMP", "bmp", supports_alpha=False),
    "TIFF": _OutputFormat("TIFF", "tiff", True),
    "ICO": _OutputFormat("ICO", "ico", True),
    "PDF": _OutputFormat("PDF", "pdf", supports_alpha=False),
}

# Other names people commonly use for the formats above.
_FORMAT_ALIASES = {
    "JPG": "JPEG",
    "TIF": "TIFF",
    "HEIF": "HEIC",
}

SUPPORTED_OUTPUT_FORMATS = tuple(_OUTPUT_FORMATS)

# Encoder settings. Pillow's defaults (e.g. JPEG quality 75) are tuned
# for size over looks; these favour visibly-lossless output.
_SAVE_OPTIONS = {
    "JPEG": {"quality": 92},
    "WEBP": {"quality": 90},
    "AVIF": {"quality": 85},
    "HEIF": {"quality": 90},
    "TIFF": {"compression": "tiff_lzw"},
    # zlib level 3 instead of Pillow's default 6: ~2.5x faster to save a
    # large (e.g. 8K) PNG for only ~8% more bytes. Still lossless.
    "PNG": {"compress_level": 3},
}

# Longest side, in pixels, of the small preview images the web UI shows.
PREVIEW_SIZE = 96

# Which colour "family" each Pillow mode belongs to — used to decide
# whether the source's embedded colour profile still applies after
# mode conversion (a CMYK profile on an RGB image would be wrong).
_COLOR_FAMILY = {
    "RGB": "rgb", "RGBA": "rgb", "P": "rgb", "PA": "rgb",
    "L": "gray", "LA": "gray", "1": "gray",
    "I": "gray", "I;16": "gray", "I;16B": "gray", "I;16L": "gray", "F": "gray",
    "CMYK": "cmyk",
}


def normalize_format(target_format: str) -> str:
    """Return the canonical output format name for `target_format`.

    Case-insensitive, accepts aliases ("jpg", "tif", "heif").

    Raises:
        ValueError: If the format isn't one Pixel Forge can write.
    """
    fmt = target_format.strip().upper().lstrip(".")
    fmt = _FORMAT_ALIASES.get(fmt, fmt)
    if fmt not in _OUTPUT_FORMATS:
        raise ValueError(
            f"Unsupported output format: {target_format!r}. Choose one of: "
            + ", ".join(SUPPORTED_OUTPUT_FORMATS)
        )
    return fmt


def output_extension(target_format: str) -> str:
    """File extension (no dot) that converted files should use."""
    return _OUTPUT_FORMATS[normalize_format(target_format)].extension


def convert_image(
    data: bytes,
    *,
    target_format: str,
    size: tuple[int, int] | None = None,
    resize_mode: ResizeMode = "fit",
    rotate: int = 0,
) -> bytes:
    """Convert image bytes to another format, with optional resize/rotate.

    Any format Pillow (plus pillow-heif) can read is accepted as input,
    including HEIC, AVIF, TIFF, ICO, PSD and TGA. Animated GIF/WEBP/PNG
    input stays animated when the output format supports animation;
    otherwise the first frame is used.

    Args:
        data: Raw bytes of the source image.
        target_format: Output format, e.g. "jpeg", "PNG", "heic"
            (case-insensitive; see SUPPORTED_OUTPUT_FORMATS).
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
            or `size` is invalid, or `target_format` isn't supported.
        PIL.UnidentifiedImageError: If `data` isn't a readable image.
    """
    return _convert(
        data,
        target_format=target_format,
        size=size,
        resize_mode=resize_mode,
        rotate=rotate,
    )[0]


def convert_image_with_preview(
    data: bytes,
    *,
    target_format: str,
    size: tuple[int, int] | None = None,
    resize_mode: ResizeMode = "fit",
    rotate: int = 0,
) -> tuple[bytes, bytes]:
    """Like convert_image(), but also return a small WEBP preview.

    The preview is made from the already-transformed image in memory,
    so it costs almost nothing — unlike decoding the (possibly 8K)
    output again afterwards.

    Returns:
        (converted bytes, preview WEBP bytes no larger than PREVIEW_SIZE).
    """
    converted, first_frame = _convert(
        data,
        target_format=target_format,
        size=size,
        resize_mode=resize_mode,
        rotate=rotate,
    )
    return converted, _make_preview(first_frame)


def _make_preview(img: Image.Image) -> bytes:
    preview = img.copy()
    # reducing_gap makes shrinking a huge image to thumbnail size cheap.
    preview.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS, reducing_gap=2.0)
    out = io.BytesIO()
    preview.save(out, format="WEBP", quality=80)
    return out.getvalue()


def _convert(
    data: bytes,
    *,
    target_format: str,
    size: tuple[int, int] | None,
    resize_mode: ResizeMode,
    rotate: int,
) -> tuple[bytes, Image.Image]:
    """Shared implementation: returns (converted bytes, first output frame)."""
    if rotate % 90 != 0:
        raise ValueError(f"rotate must be a multiple of 90, got {rotate}")
    if resize_mode not in ("fit", "stretch"):
        raise ValueError(
            f"resize_mode must be 'fit' or 'stretch', got {resize_mode!r}"
        )
    if size is not None:
        _validate_size(size)

    spec = _OUTPUT_FORMATS[normalize_format(target_format)]

    with Image.open(io.BytesIO(data)) as src:
        src.load()  # force full read now, so corrupt data fails here
        icc_profile = src.info.get("icc_profile")
        source_family = _COLOR_FAMILY.get(src.mode)

        frame_count = getattr(src, "n_frames", 1)
        if spec.supports_animation and frame_count > 1:
            frames, durations = [], []
            for frame in ImageSequence.Iterator(src):
                durations.append(frame.info.get("duration", 100))
                frames.append(
                    _prepare_frame(frame.copy(), spec, size, resize_mode, rotate)
                )
                if len(frames) == 1:
                    _check_animation_budget(frames[0].size, frame_count)
            converted = _save(
                frames[0],
                spec,
                _keep_profile(icc_profile, source_family, frames[0]),
                append_images=frames[1:],
                duration=durations,
                loop=src.info.get("loop", 0),
            )
            return converted, frames[0]

        img = _prepare_frame(src, spec, size, resize_mode, rotate)
        return _save(img, spec, _keep_profile(icc_profile, source_family, img)), img


def _validate_size(size: tuple[int, int]) -> None:
    width, height = size
    if width < 1 or height < 1:
        raise ValueError("Width and height must be at least 1 pixel")
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise ValueError(
            f"Width and height can be at most {MAX_DIMENSION} pixels"
        )


def _prepare_frame(
    img: Image.Image,
    spec: _OutputFormat,
    size: tuple[int, int] | None,
    resize_mode: ResizeMode,
    rotate: int,
) -> Image.Image:
    """Apply orientation, rotate, resize and colour-mode fixes to one frame."""
    # Normalize any embedded EXIF orientation tag before we apply our
    # own explicit rotation, so the two don't stack.
    img = ImageOps.exif_transpose(img)

    # Get into a standard 8-bit mode first, so resizing and every
    # encoder downstream only ever sees L / LA / RGB / RGBA.
    img = _to_standard_mode(img)

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

    # Formats without alpha support get transparency flattened onto
    # white — a naive convert("RGB") would turn it black or garbage.
    if not spec.supports_alpha and img.mode in ("RGBA", "LA"):
        img = _flatten_onto_white(img)

    return img


def _to_standard_mode(img: Image.Image) -> Image.Image:
    """Convert any Pillow mode to one of L, LA, RGB or RGBA.

    Covers the modes that used to crash specific encoders: CMYK (print
    JPEGs) into PNG/GIF, 16-bit and 32-bit grayscale (scientific /
    medical PNGs and TIFFs) into JPEG/BMP, palette-with-alpha ("PA"),
    1-bit black & white, and floating-point images.
    """
    mode = img.mode
    if mode in ("L", "LA", "RGB", "RGBA"):
        return img
    if mode == "1":
        return img.convert("L")
    if mode == "F" or mode.startswith("I"):
        return _to_8bit_grayscale(img)
    if mode == "PA" or (mode == "P" and "transparency" in img.info):
        return img.convert("RGBA")
    # P without transparency, CMYK, YCbCr, LAB, HSV, RGBX, ...
    return img.convert("RGB")


def _to_8bit_grayscale(img: Image.Image) -> Image.Image:
    """Scale a high-bit-depth or float grayscale image down to 8-bit "L".

    A plain convert("L") would clip everything above 255 to white,
    blowing out almost every 16-bit image.
    """
    if img.mode == "F":
        low, high = img.getextrema()
        scale = 255 / (high - low) if high > low else 1
        img = img.point(lambda v: v * scale - low * scale)
    else:
        img = img.convert("I")
        if img.getextrema()[1] > 255:
            img = img.point(lambda v: v * (1 / 256))
    return img.convert("L")


def _flatten_onto_white(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background.convert("L") if img.mode == "LA" else background


def _keep_profile(
    icc_profile: bytes | None, source_family: str | None, img: Image.Image
) -> bytes | None:
    """Return the source ICC profile if it still matches `img`'s colours.

    Keeping it matters for iPhone HEIC photos (Display P3): dropping
    the profile makes colours look washed out after conversion.
    """
    if icc_profile and source_family == _COLOR_FAMILY.get(img.mode):
        return icc_profile
    return None


def _check_animation_budget(frame_size: tuple[int, int], frame_count: int) -> None:
    width, height = frame_size
    if width * height * frame_count > _MAX_ANIMATION_PIXELS:
        raise ValueError(
            "Animation is too large at this size — try a smaller target "
            "size or a non-animated output format"
        )


def _save(
    img: Image.Image,
    spec: _OutputFormat,
    icc_profile: bytes | None,
    **animation,
) -> bytes:
    options = dict(_SAVE_OPTIONS.get(spec.pillow_name, {}))
    if icc_profile:
        options["icc_profile"] = icc_profile
    if animation:
        options.update(animation, save_all=True)
        # Each frame is a complete picture, so clear the previous one
        # first; otherwise transparent areas show stale frames through.
        if spec.pillow_name == "GIF":
            options["disposal"] = 2
        elif spec.pillow_name == "PNG":
            options["disposal"] = 1

    out = io.BytesIO()
    img.save(out, format=spec.pillow_name, **options)
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
