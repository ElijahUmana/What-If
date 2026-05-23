"""IngestAgent -- captures a YouTube live stream into chunks + frames."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from agents.ingest.chunk_indexer import ChunkIndexer
from agents.ingest.ffmpeg_pipeline import FFmpegCapture
from agents.ingest.frame_ring import FrameRing
from agents.ingest.youtube_resolver import resolve_manifest

logger = logging.getLogger(__name__)

_BACKOFF_SCHEDULE = [2, 5, 15, 60]  # seconds


class IngestAgent:
    """Orchestrates live-stream capture for a single YouTube URL.

    Lifecycle:
        agent = IngestAgent(...)
        await agent.run()   # blocks until stopped or unrecoverable failure
        agent.stop()        # idempotent
    """

    def __init__(
        self,
        session_id: str,
        youtube_url: str,
        work_dir: str | Path,
    ) -> None:
        self.session_id = session_id
        self.youtube_url = youtube_url
        self.work_dir = Path(work_dir)

        self.session_dir = self.work_dir / "sessions" / session_id
        self.frame_ring = FrameRing(max_frames=600)

        self._capture: FFmpegCapture | None = None
        self._indexer: ChunkIndexer | None = None
        self._stop_event = asyncio.Event()
        self._frame_counter = 0

    # ------------------------------------------------------------------
    # Callbacks (run on watchdog thread -- keep fast)
    # ------------------------------------------------------------------

    def _on_chunk(self, chunk_path: str, seq: int) -> None:
        logger.info("[ingest:%s] chunk %d: %s", self.session_id, seq, chunk_path)
        print(f"[chunk] seq={seq} path={chunk_path}")

    def _on_frame(self, frame_path: str, seq: int) -> None:
        logger.info("[ingest:%s] frame %d: %s", self.session_id, seq, frame_path)
        print(f"[frame] seq={seq} path={frame_path}")

        # Read JPEG bytes and push into the ring buffer
        try:
            jpeg_bytes = Path(frame_path).read_bytes()
            pts_ms = int(seq * (1000 / 2))  # approximate PTS from 2-fps sequence
            self.frame_ring.append(pts_ms, jpeg_bytes)
            self._frame_counter += 1
        except Exception as exc:
            logger.warning("Failed to read frame %s: %s", frame_path, exc)

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Resolve, capture, and auto-restart on failure with backoff."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        backoff_idx = 0

        while not self._stop_event.is_set():
            # 1. Resolve manifest
            try:
                manifest_url = await asyncio.to_thread(
                    resolve_manifest, self.youtube_url
                )
            except RuntimeError as exc:
                logger.error("Manifest resolution failed: %s", exc)
                delay = _BACKOFF_SCHEDULE[min(backoff_idx, len(_BACKOFF_SCHEDULE) - 1)]
                backoff_idx += 1
                logger.info("Backing off %ds before retry...", delay)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                continue

            # 2. Start ffmpeg capture
            self._capture = FFmpegCapture(
                manifest_url=manifest_url,
                session_dir=self.session_dir,
                chunk_seconds=2,
                frame_fps=2,
            )
            self._capture.start()

            # 3. Start watchdog indexer
            self._indexer = ChunkIndexer(
                session_id=self.session_id,
                session_dir=self.session_dir,
                on_chunk_callback=self._on_chunk,
                on_frame_callback=self._on_frame,
            )
            self._indexer.start()

            # Reset backoff on successful start
            backoff_idx = 0

            # 4. Poll until ffmpeg dies or we are told to stop
            while not self._stop_event.is_set():
                if not self._capture.is_alive():
                    rc = self._capture.returncode
                    logger.warning(
                        "ffmpeg exited (rc=%s), will re-resolve and restart", rc
                    )
                    break
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass

            # 5. Cleanup before potential restart
            if self._indexer is not None:
                self._indexer.stop()
            if self._capture is not None and self._capture.is_alive():
                self._capture.stop()

            if self._stop_event.is_set():
                break

            # 6. Backoff before restart
            delay = _BACKOFF_SCHEDULE[min(backoff_idx, len(_BACKOFF_SCHEDULE) - 1)]
            backoff_idx += 1
            logger.info("Restarting capture in %ds...", delay)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        """Signal the agent to shut down."""
        self._stop_event.set()
        if self._capture is not None:
            self._capture.stop()
        if self._indexer is not None:
            self._indexer.stop()
        logger.info("IngestAgent stopped (session=%s)", self.session_id)
