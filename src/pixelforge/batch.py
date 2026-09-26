"""Batch runner.

Applies core.convert_image() to a set of uploaded files and collects
a summary report (processed / skipped / errored) instead of letting a
single bad file crash the run. Used by the web app's multi-file
upload handler.

Deliberately takes plain (filename, bytes) pairs rather than Flask's
FileStorage objects, so this module has zero web-framework dependency
and can be tested and reused on its own.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Literal

from pixelforge.core import (
    convert_image,
    convert_image_with_preview,
    output_extension,
)
from PIL import Image, UnidentifiedImageError

Status = Literal["success", "skipped", "error"]


@dataclass
class FileResult:
    """Outcome for a single file in a batch run."""

    filename: str
    status: Status
    message: str = ""
    output_filename: str | None = None
    data: bytes | None = None
    preview: bytes | None = None  # small WEBP, only when requested


@dataclass
class BatchSummary:
    """Collected results for an entire batch run."""

    results: list[FileResult] = field(default_factory=list)

    @property
    def succeeded(self) -> list[FileResult]:
        return [r for r in self.results if r.status == "success"]

    @property
    def skipped(self) -> list[FileResult]:
        return [r for r in self.results if r.status == "skipped"]

    @property
    def errored(self) -> list[FileResult]:
        return [r for r in self.results if r.status == "error"]

    def counts(self) -> dict[str, int]:
        return {
            "success": len(self.succeeded),
            "skipped": len(self.skipped),
            "error": len(self.errored),
        }


def default_workers() -> int:
    """How many files to convert at once.

    Pillow and pillow-heif release Python's GIL while decoding, resizing
    and encoding, so plain threads give a real speed-up. Capped at 8
    because each worker can hold several hundred MB when producing 8K
    output. Override with the PIXELFORGE_WORKERS environment variable.
    """
    configured = os.environ.get("PIXELFORGE_WORKERS")
    if configured:
        return max(1, int(configured))
    return max(1, min(8, os.cpu_count() or 1))


def convert_batch(
    files: list[tuple[str, bytes]],
    *,
    target_format: str,
    size: tuple[int, int] | None = None,
    resize_mode: str = "fit",
    rotate: int = 0,
    strict: bool = False,
    with_previews: bool = False,
    max_workers: int | None = None,
) -> BatchSummary:
    """Convert a batch of in-memory files, collecting a per-file result.

    Files are converted in parallel, but results always come back in
    the same order as `files`, and output names are assigned in that
    order too, so the outcome is identical to a one-at-a-time run.

    Args:
        files: List of (filename, data) pairs.
        target_format / size / resize_mode / rotate: Passed straight
            through to core.convert_image() for every file.
        strict: If True, the first error (in input order) is raised
            instead of being caught and recorded — for CI-style
            hard-fail runs. Default False: skip bad files, keep going,
            report at the end.
        with_previews: Also produce a small WEBP preview per success
            (FileResult.preview), for UIs that show thumbnails.
        max_workers: Files converted at once; defaults to
            default_workers(). 1 means strictly sequential.

    Returns:
        A BatchSummary with exactly one FileResult per input file
        (empty-batch input returns an empty summary, not an error).
    """
    convert = convert_image_with_preview if with_previews else convert_image

    def run(data: bytes):
        return convert(
            data,
            target_format=target_format,
            size=size,
            resize_mode=resize_mode,
            rotate=rotate,
        )

    workers = max_workers or default_workers()
    summary = BatchSummary()
    used_names: set[str] = set()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, data) if data else None for _, data in files]
        try:
            for (filename, _), future in zip(files, futures):
                if future is None:
                    summary.results.append(
                        FileResult(filename, "skipped", "Empty file")
                    )
                    continue

                try:
                    outcome = future.result()
                except UnidentifiedImageError:
                    if strict:
                        raise
                    summary.results.append(
                        FileResult(filename, "error", "Not a valid image file")
                    )
                    continue
                except Exception as exc:
                    if strict:
                        raise
                    summary.results.append(
                        FileResult(filename, "error", _friendly_error(exc))
                    )
                    continue

                converted, preview = outcome if with_previews else (outcome, None)
                output_name = _unique_name(
                    _replace_extension(filename, target_format), used_names
                )
                used_names.add(output_name)
                summary.results.append(
                    FileResult(
                        filename,
                        "success",
                        output_filename=output_name,
                        data=converted,
                        preview=preview,
                    )
                )
        finally:
            # On a strict-mode raise, don't start files still queued.
            for future in futures:
                if future is not None:
                    future.cancel()

    return summary


def _friendly_error(exc: Exception) -> str:
    """Turn an exception into a short message a non-programmer can act on."""
    if isinstance(exc, Image.DecompressionBombError):
        return "Image is too large to process safely"
    if isinstance(exc, MemoryError):
        return "Not enough memory to convert this image — try a smaller size"
    if isinstance(exc, ValueError):
        # Our own validation errors are already written for users.
        return str(exc)
    if isinstance(exc, (OSError, SyntaxError)):
        # Pillow raises these for damaged/truncated files and for
        # images it can open but not decode.
        return "File is damaged or uses an unsupported variant of its format"
    return "Could not convert this image"


def _replace_extension(filename: str, target_format: str) -> str:
    """Swap filename's extension for one matching target_format."""
    ext = output_extension(target_format)
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return f"{stem}.{ext}"


def _unique_name(name: str, used: set[str]) -> str:
    """Return `name`, or a "(1)", "(2)", ... suffixed variant if taken."""
    if name not in used:
        return name
    stem, _, ext = name.rpartition(".")
    counter = 1
    candidate = f"{stem} ({counter}).{ext}"
    while candidate in used:
        counter += 1
        candidate = f"{stem} ({counter}).{ext}"
    return candidate
