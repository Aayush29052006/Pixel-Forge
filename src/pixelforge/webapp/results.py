"""In-memory store for converted batches.

/api/convert keeps its output here and hands the page a batch id, so
individual downloads and "Download All (ZIP)" can be served from what
was already converted — instead of the browser re-uploading every file
and the server converting the whole batch a second time.

Memory is bounded: batches are evicted oldest-first once the total
size passes a byte budget, but the newest batch is always kept, so a
single huge batch still works. After eviction the page gets a 404 and
asks the user to convert again.
"""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredFile:
    filename: str
    data: bytes


class ResultStore:
    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._batches: OrderedDict[str, list[StoredFile]] = OrderedDict()
        self._total = 0
        self._lock = threading.Lock()

    def add(self, files: list[StoredFile]) -> str:
        """Store a batch and return its id."""
        batch_id = secrets.token_urlsafe(12)
        size = sum(len(f.data) for f in files)
        with self._lock:
            self._batches[batch_id] = files
            self._total += size
            while self._total > self._max_bytes and len(self._batches) > 1:
                _, evicted = self._batches.popitem(last=False)
                self._total -= sum(len(f.data) for f in evicted)
        return batch_id

    def get(self, batch_id: str) -> list[StoredFile] | None:
        with self._lock:
            return self._batches.get(batch_id)
