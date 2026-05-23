"""VideoGenAgent -- generates counterfactual clips via Veo 3.1."""

from __future__ import annotations

import asyncio
import logging
import time

from google import genai
from google.genai import types

from agents._lib.gemini import get_client
from agents._lib.trace import trace_span

logger = logging.getLogger(__name__)

_MODEL = "veo-3.1-fast-generate-preview"


async def generate_clip(
    prompt_text: str,
    reference_frames: list[bytes],
    session_id: str = "",
) -> tuple[bytes, dict]:
    """Generate a counterfactual video clip via Veo 3.1.

    Args:
        prompt_text: Natural-language Veo prompt (from prompt_builder).
        reference_frames: Up to 3 JPEG reference frames for visual continuity.

    Returns:
        Tuple of (mp4_bytes, metadata_dict).
    """
    def _sync_generate():
        client = get_client()

        refs = []
        for fb in reference_frames[:3]:
            refs.append(
                types.VideoGenerationReferenceImage(
                    image=types.Image(
                        image_bytes=fb, mime_type="image/jpeg"
                    ),
                    reference_type="asset",
                )
            )

        operation = client.models.generate_videos(
            model=_MODEL,
            prompt=prompt_text,
            config=types.GenerateVideosConfig(
                reference_images=refs if refs else None,
                aspect_ratio="16:9",
                resolution="720p",
            ),
        )

        started = time.time()
        while not operation.done:
            elapsed = time.time() - started
            # Poll faster once past the initial queue wait
            time.sleep(10 if elapsed < 30 else 5)
            operation = client.operations.get(operation)

        video = operation.response.generated_videos[0]
        video_data = client.files.download(file=video.video)
        mp4_bytes = (
            video_data.read() if hasattr(video_data, "read") else video_data
        )

        latency_s = time.time() - started
        metadata = {
            "model": _MODEL,
            "latency_s": latency_s,
            "ref_frame_count": len(refs),
            "prompt_length": len(prompt_text),
        }
        return mp4_bytes, metadata

    with trace_span("videogen", "generate_clip", session_id=session_id) as span:
        mp4_bytes, metadata = await asyncio.to_thread(_sync_generate)
        span["payload"].update(metadata)
        logger.info(
            "Veo generation completed in %.1fs (model=%s)",
            metadata["latency_s"],
            _MODEL,
        )
        return mp4_bytes, metadata
