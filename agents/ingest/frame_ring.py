"""Thread-safe ring buffer of recent JPEG frames keyed by PTS."""

from __future__ import annotations

import threading
from collections import deque
from typing import TypedDict


class FrameEntry(TypedDict):
    pts_ms: int
    jpeg_bytes: bytes


class FrameRing:
    """Fixed-capacity ring buffer holding the most recent JPEG frames.

    Default capacity of 600 frames = 5 minutes at 2 fps.
    All public methods are thread-safe.
    """

    def __init__(self, max_frames: int = 600) -> None:
        self._max = max_frames
        self._buf: deque[FrameEntry] = deque(maxlen=max_frames)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, pts_ms: int, jpeg_bytes: bytes) -> None:
        """Add a frame. Oldest frame is evicted when capacity is reached."""
        with self._lock:
            self._buf.append(FrameEntry(pts_ms=pts_ms, jpeg_bytes=jpeg_bytes))

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def window(self, start_pts_ms: int, end_pts_ms: int) -> list[FrameEntry]:
        """Return frames whose PTS falls within [start, end] inclusive."""
        with self._lock:
            return [
                f for f in self._buf
                if start_pts_ms <= f["pts_ms"] <= end_pts_ms
            ]

    def last_n_seconds(self, seconds: float) -> list[FrameEntry]:
        """Return frames from the last *seconds* seconds relative to the
        newest frame in the buffer."""
        with self._lock:
            if not self._buf:
                return []
            latest_pts = self._buf[-1]["pts_ms"]
            cutoff = latest_pts - int(seconds * 1000)
            return [f for f in self._buf if f["pts_ms"] >= cutoff]

    def latest(self) -> FrameEntry | None:
        """Return the most recent frame, or None if empty."""
        with self._lock:
            if not self._buf:
                return None
            return self._buf[-1]

    def __len__(self) -> int:
        with self._lock:
            return len(self._buf)
