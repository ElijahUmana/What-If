"""Test captioner against a real captured frame. Run: GEMINI_API_KEY=... python -m agents.test_captioner"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


async def main():
    from agents.captioner.agent import caption_frame

    frame_path = "/tmp/whatif_smoke/frames/f_00020.jpg"
    if not os.path.exists(frame_path):
        print(f"No test frame at {frame_path}. Run the ingest smoke test first.")
        return
    with open(frame_path, "rb") as f:
        frame_bytes = f.read()
    result = await caption_frame(frame_bytes)
    print(f"Caption: {result}")
    assert "caption" in result, f"Missing 'caption' key in result: {result}"
    assert "ball_visible" in result, f"Missing 'ball_visible' key in result: {result}"
    assert "scene_type" in result, f"Missing 'scene_type' key in result: {result}"
    assert "confidence" in result, f"Missing 'confidence' key in result: {result}"
    assert "players_visible_count" in result, (
        f"Missing 'players_visible_count' key in result: {result}"
    )
    print("CAPTIONER TEST PASSED")


if __name__ == "__main__":
    os.environ.setdefault(
        "GEMINI_API_KEY", "AIzaSyA0v4wwB12o8feLgv7Xbe5nYAD6ga9cvVw"
    )
    asyncio.run(main())
