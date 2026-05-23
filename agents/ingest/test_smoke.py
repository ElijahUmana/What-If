"""Smoke test for the ingest pipeline.

Run:  python -m agents.ingest.test_smoke
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# Ensure the project root is on sys.path so `agents.ingest` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from agents.ingest.agent import IngestAgent  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> None:
    url = os.environ.get(
        "YOUTUBE_DEMO_URL",
        "https://www.youtube.com/watch?v=ZS7-0zjC_rg",
    )
    work_dir = "/tmp/whatif"
    session = "smoke_test"

    agent = IngestAgent(session_id=session, youtube_url=url, work_dir=work_dir)

    try:
        # yt-dlp resolve can take ~40s, then we need ~20s of capture.
        # Total budget: 90s.
        await asyncio.wait_for(agent.run(), timeout=90)
    except asyncio.TimeoutError:
        agent.stop()

    # Give watchdog a moment to flush pending events
    await asyncio.sleep(1)

    # --- assertions ---
    chunks_dir = os.path.join(work_dir, "sessions", session, "chunks")
    frames_dir = os.path.join(work_dir, "sessions", session, "frames")

    chunks = [f for f in os.listdir(chunks_dir) if f.endswith(".ts")]
    frames = [f for f in os.listdir(frames_dir) if f.endswith(".jpg")]

    print(f"\nCaptured {len(chunks)} chunks, {len(frames)} frames")
    print(f"FrameRing size: {len(agent.frame_ring)}")

    assert len(chunks) > 5, f"Expected >5 chunks, got {len(chunks)}"
    assert len(frames) > 20, f"Expected >20 frames, got {len(frames)}"
    print("\nSMOKE TEST PASSED")


if __name__ == "__main__":
    asyncio.run(main())
