"""Launch ffmpeg to capture a live HLS stream into .ts chunks and .jpg frames."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_FFMPEG = "/opt/homebrew/bin/ffmpeg"


class FFmpegCapture:
    """Manages an ffmpeg subprocess that simultaneously segments video into
    .ts chunks and extracts JPEG frames from a live HLS manifest."""

    def __init__(
        self,
        manifest_url: str,
        session_dir: str | Path,
        chunk_seconds: int = 2,
        frame_fps: int = 2,
    ) -> None:
        self.manifest_url = manifest_url
        self.session_dir = Path(session_dir)
        self.chunk_seconds = chunk_seconds
        self.frame_fps = frame_fps
        self._proc: subprocess.Popen | None = None

        self.chunks_dir = self.session_dir / "chunks"
        self.frames_dir = self.session_dir / "frames"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Create output directories and launch the ffmpeg process."""
        if self._proc is not None and self._proc.poll() is None:
            raise RuntimeError("FFmpegCapture already running")

        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            _FFMPEG, "-y",
            # reconnect options for live streams
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "30",
            # input
            "-i", self.manifest_url,
            # --- output 1: segmented .ts chunks (copy, no re-encode) ---
            "-map", "0:v",
            "-c:v", "copy",
            "-f", "segment",
            "-segment_time", str(self.chunk_seconds),
            "-segment_format", "mpegts",
            "-reset_timestamps", "1",
            str(self.chunks_dir / "c_%05d.ts"),
            # --- output 2: JPEG frames ---
            "-map", "0:v",
            "-vf", f"fps={self.frame_fps},scale=1280:720",
            "-q:v", "4",
            str(self.frames_dir / "f_%08d.jpg"),
        ]

        logger.info("FFmpegCapture.start: %s", " ".join(cmd))

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        logger.info("FFmpegCapture started (pid=%d)", self._proc.pid)

    def stop(self) -> None:
        """Send SIGTERM to the ffmpeg process and wait for it to exit."""
        if self._proc is None:
            return
        if self._proc.poll() is not None:
            return
        logger.info("FFmpegCapture.stop: sending SIGTERM to pid=%d", self._proc.pid)
        self._proc.send_signal(signal.SIGTERM)
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("FFmpegCapture: SIGTERM timed out, sending SIGKILL")
            self._proc.kill()
            self._proc.wait(timeout=5)

    def is_alive(self) -> bool:
        """Return True if the ffmpeg process is still running."""
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the ffmpeg process to terminate.

        Returns:
            The process return code.

        Raises:
            subprocess.TimeoutExpired: If *timeout* seconds elapse.
            RuntimeError: If no process has been started.
        """
        if self._proc is None:
            raise RuntimeError("FFmpegCapture not started")
        return self._proc.wait(timeout=timeout)

    @property
    def returncode(self) -> int | None:
        """The ffmpeg process return code, or None if still running."""
        if self._proc is None:
            return None
        return self._proc.poll()

    @property
    def pid(self) -> int | None:
        """PID of the running ffmpeg process."""
        if self._proc is None:
            return None
        return self._proc.pid
