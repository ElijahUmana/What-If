"""Watch for new .ts chunks and .jpg frames via watchdog, invoking callbacks."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

_FFPROBE = "/opt/homebrew/bin/ffprobe"

# Callbacks
ChunkCallback = Callable[[str, int], None]   # (chunk_path, sequence_num)
FrameCallback = Callable[[str, int], None]   # (frame_path, frame_num)


def _probe_pts(chunk_path: str) -> dict | None:
    """Extract start_time and duration from a .ts chunk via ffprobe.

    Returns a dict with keys ``start_time`` and ``duration`` (floats),
    or None if probing fails.
    """
    cmd = [
        _FFPROBE,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        chunk_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        return {
            "start_time": float(fmt.get("start_time", 0)),
            "duration": float(fmt.get("duration", 0)),
        }
    except Exception as exc:
        logger.debug("ffprobe failed for %s: %s", chunk_path, exc)
        return None


class _Handler(FileSystemEventHandler):
    """Dispatch file-creation events to chunk/frame callbacks."""

    def __init__(
        self,
        on_chunk: ChunkCallback | None,
        on_frame: FrameCallback | None,
    ) -> None:
        super().__init__()
        self._on_chunk = on_chunk
        self._on_frame = on_frame
        self._chunk_seq = 0
        self._frame_seq = 0
        self._lock = threading.Lock()

    def on_created(self, event: FileCreatedEvent) -> None:  # type: ignore[override]
        if event.is_directory:
            return

        path = event.src_path

        if path.endswith(".ts") and self._on_chunk:
            with self._lock:
                seq = self._chunk_seq
                self._chunk_seq += 1
            # Fire-and-forget PTS probe (non-blocking for the watcher thread)
            pts = _probe_pts(path)
            if pts:
                logger.debug(
                    "chunk %d: start=%.3f dur=%.3f %s",
                    seq, pts["start_time"], pts["duration"], path,
                )
            self._on_chunk(path, seq)

        elif path.endswith(".jpg") and self._on_frame:
            with self._lock:
                seq = self._frame_seq
                self._frame_seq += 1
            self._on_frame(path, seq)


class ChunkIndexer:
    """Watches session chunks/ and frames/ directories and fires callbacks
    when new files appear."""

    def __init__(
        self,
        session_id: str,
        session_dir: str | Path,
        on_chunk_callback: ChunkCallback | None = None,
        on_frame_callback: FrameCallback | None = None,
    ) -> None:
        self.session_id = session_id
        self.session_dir = Path(session_dir)
        self._on_chunk = on_chunk_callback
        self._on_frame = on_frame_callback
        self._observer: Observer | None = None

    def start(self) -> None:
        """Start watching for new chunks and frames."""
        handler = _Handler(self._on_chunk, self._on_frame)
        self._observer = Observer()

        chunks_dir = self.session_dir / "chunks"
        frames_dir = self.session_dir / "frames"

        # Ensure directories exist before scheduling watches
        chunks_dir.mkdir(parents=True, exist_ok=True)
        frames_dir.mkdir(parents=True, exist_ok=True)

        self._observer.schedule(handler, str(chunks_dir), recursive=False)
        self._observer.schedule(handler, str(frames_dir), recursive=False)
        self._observer.start()
        logger.info(
            "ChunkIndexer started for session=%s dir=%s",
            self.session_id, self.session_dir,
        )

    def stop(self) -> None:
        """Stop the watchdog observer."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            logger.info("ChunkIndexer stopped for session=%s", self.session_id)
