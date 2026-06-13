"""
Lightweight idempotency / delivery-dedup store for webhook processing.

GitHub redelivers webhooks (and PR `synchronize` events fire repeatedly), so
the same logical review can arrive multiple times. Processing each one runs the
full multi-agent chain and posts a duplicate review. This module records which
keys have already been accepted so the handler can skip duplicates.

The default backend is an in-process store with file-backed persistence for
survival across Cloud Run cold starts. For multi-instance deployments, swap
this with a shared store (Redis, Firestore, Cloud Tasks dedup).
"""

from __future__ import annotations

import threading
from collections import OrderedDict

from src.config import STATE_DIR


class InMemoryIdempotencyStore:
    """Bounded, thread-safe set of seen keys with FIFO eviction and file-backed
    persistence for survival across process restarts (Cloud Run cold starts).

    The file-backed layer is a best-effort log — writes are synchronous for
    durability but reads only happen on first access (lazy-load from disk).
    """

    _DISK_FILE = STATE_DIR / ".webhook_dedup_log"

    def __init__(self, max_size: int = 10_000) -> None:
        self._max_size = max_size
        self._seen: "OrderedDict[str, None]" = OrderedDict()
        self._lock = threading.Lock()
        self._loaded_from_disk = False

    def _load_from_disk(self) -> None:
        """Restore seen keys from the disk log on first access."""
        if self._loaded_from_disk:
            return
        self._loaded_from_disk = True
        try:
            if not self._DISK_FILE.exists():
                return
            with open(self._DISK_FILE) as f:
                for line in f:
                    key = line.strip()
                    if key and len(self._seen) < self._max_size:
                        self._seen[key] = None
        except Exception:
            pass

    def _append_to_disk(self, key: str) -> None:
        """Best-effort write of a single key to the disk log."""
        try:
            self._DISK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self._DISK_FILE, "a") as f:
                f.write(key + "\n")
        except Exception:
            pass

    def seen(self, key: str) -> bool:
        """Return True if the key was already recorded."""
        with self._lock:
            self._load_from_disk()
            return key in self._seen

    def add(self, key: str) -> bool:
        """Record a key. Returns True if newly added, False if already exists."""
        with self._lock:
            self._load_from_disk()
            if key in self._seen:
                self._seen.move_to_end(key)
                return False
            self._seen[key] = None
            while len(self._seen) > self._max_size:
                self._seen.popitem(last=False)
            self._append_to_disk(key)
            return True


def build_delivery_key(
    delivery_id: str,
    repo_full_name: str,
    pr_number: int | None,
    head_sha: str,
) -> str:
    """Build a stable dedup key for a webhook delivery.

    Prefer the GitHub delivery id when present (covers exact redeliveries).
    Always include (repo, pr, head_sha) so repeated `synchronize` events for the
    same commit are also collapsed even across distinct delivery ids.
    """
    base = f"{repo_full_name}#{pr_number}@{head_sha}"
    return f"{delivery_id}|{base}" if delivery_id else base


# Module-level default store used by the webhook handler.
default_store = InMemoryIdempotencyStore()
