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

from dataclasses import dataclass, field
from typing import Literal

from pixelforge.core import convert_image

Status = Literal["success", "skipped", "error"]


@dataclass
class FileResult:
    """Outcome for a single file in a batch run."""

    filename: str
    status: Status
    message: str = ""
    output_filename: str | None = None
    data: bytes | None = None


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


def convert_batch(
    files: list[tuple[str, bytes]],
    *,
    target_format: str,
    size: tuple[int, int] | None = None,
    resize_mode: str = "fit",
    rotate: int = 0,
    strict: bool = False,
) -> BatchSummary:
    """Convert a batch of in-memory files, collecting a per-file result.

    Args:
        files: List of (filename, data) pairs.
        target_format / size / resize_mode / rotate: Passed straight
            through to core.convert_image() for every file.
        strict: If True, the first error is raised immediately instead
            of being caught and recorded — for CI-style hard-fail runs.
            Default False: skip bad files, keep going, report at the end.

    Returns:
        A BatchSummary with exactly one FileResult per input file
        (empty-batch input returns an empty summary, not an error).
    """
    summary = BatchSummary()
    used_names: set[str] = set()

    for filename, data in files:
        if not data:
            summary.results.append(FileResult(filename, "skipped", "Empty file"))
            continue

        try:
            converted = convert_image(
                data,
                target_format=target_format,
                size=size,
                resize_mode=resize_mode,
                rotate=rotate,
            )
        except Exception as exc:
            if strict:
                raise
            summary.results.append(FileResult(filename, "error", str(exc)))
            continue

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
            )
        )

    return summary


def _replace_extension(filename: str, target_format: str) -> str:
    """Swap filename's extension for one matching target_format."""
    ext = target_format.lower()
    if ext == "jpeg":
        ext = "jpg"
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
