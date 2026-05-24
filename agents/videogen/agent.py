"""VideoGenAgent -- generates counterfactual clips via Veo 3.1."""

from __future__ import annotations

import asyncio
import io
import logging
import time

from PIL import Image
from google import genai
from google.genai import types

from agents._lib.gemini import get_client
from agents._lib.trace import trace_span

logger = logging.getLogger(__name__)

_MODEL = "veo-3.1-lite-generate-preview"

# Veo operation timeout: 5 minutes (generation typically takes 60-90s)
_VEO_TIMEOUT_S = 300

# Retries for transient Veo API failures
_VEO_MAX_RETRIES = 2


def _jpeg_to_png(jpeg_bytes: bytes) -> bytes:
    """Convert JPEG bytes to PNG to avoid double JPEG compression artifacts
    when sending reference frames to Veo."""
    img = Image.open(io.BytesIO(jpeg_bytes))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def generate_clip(
    prompt_text: str,
    reference_frames: list[bytes],
    session_id: str = "",
) -> tuple[bytes, dict]:
    """Generate a counterfactual video clip via Veo 3.1.

    Args:
        prompt_text: Natural-language Veo prompt (from prompt_builder).
        reference_frames: Up to 3 JPEG reference frames for visual continuity.
            Converted to PNG internally to avoid double JPEG compression.

    Returns:
        Tuple of (mp4_bytes, metadata_dict).
    """
    def _sync_generate():
        client = get_client()

        # Convert JPEG reference frames to PNG for better quality conditioning
        refs = []
        for fb in reference_frames[:3]:
            try:
                png_bytes = _jpeg_to_png(fb)
                refs.append(
                    types.VideoGenerationReferenceImage(
                        image=types.Image(
                            image_bytes=png_bytes, mime_type="image/png"
                        ),
                        reference_type="asset",
                    )
                )
            except Exception as e:
                logger.warning(
                    "Failed to convert reference frame to PNG, using JPEG: %s", e
                )
                refs.append(
                    types.VideoGenerationReferenceImage(
                        image=types.Image(
                            image_bytes=fb, mime_type="image/jpeg"
                        ),
                        reference_type="asset",
                    )
                )

        # Phase 1: Submit -- retry on failure, but never resubmit once
        # generation has been accepted (to avoid double-billing).
        operation = None
        last_error = None
        submit_attempt = 0
        for submit_attempt in range(_VEO_MAX_RETRIES + 1):
            try:
                operation = client.models.generate_videos(
                    model=_MODEL,
                    prompt=prompt_text,
                    config=types.GenerateVideosConfig(
                        reference_images=refs if refs else None,
                        aspect_ratio="16:9",
                        resolution="720p",
                    ),
                )
                break  # Submit succeeded
            except Exception as e:
                last_error = e
                if submit_attempt < _VEO_MAX_RETRIES:
                    wait = (submit_attempt + 1) * 10
                    logger.warning(
                        "Veo submit failed (attempt %d/%d), retrying in %ds: %s",
                        submit_attempt + 1, _VEO_MAX_RETRIES + 1, wait, e,
                    )
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"Veo submit failed after {_VEO_MAX_RETRIES + 1} attempts: {last_error}"
                    ) from last_error

        # Phase 2: Poll + download -- retry the SAME operation ID,
        # never resubmit a new generation.
        started = time.time()
        last_error = None
        for attempt in range(_VEO_MAX_RETRIES + 1):
            try:
                while not operation.done:
                    elapsed = time.time() - started
                    if elapsed > _VEO_TIMEOUT_S:
                        raise TimeoutError(
                            f"Veo generation timed out after {_VEO_TIMEOUT_S}s"
                        )
                    # Poll faster once past the initial queue wait
                    time.sleep(10 if elapsed < 30 else 5)
                    try:
                        operation = client.operations.get(operation)
                    except Exception as poll_err:
                        logger.warning(
                            "Veo poll error, retrying: %s", poll_err,
                        )
                        time.sleep(5)
                        operation = client.operations.get(operation)

                if not operation.response or not operation.response.generated_videos:
                    raise RuntimeError(
                        "Veo returned empty response (no generated videos)"
                    )

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
                    "ref_format": "png",
                    "prompt_length": len(prompt_text),
                    "submit_attempt": submit_attempt + 1,
                    "download_attempt": attempt + 1,
                }
                return mp4_bytes, metadata

            except TimeoutError:
                raise  # Don't retry timeouts
            except Exception as e:
                last_error = e
                if attempt < _VEO_MAX_RETRIES:
                    wait = (attempt + 1) * 10
                    logger.warning(
                        "Veo poll/download failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1, _VEO_MAX_RETRIES + 1, wait, e,
                    )
                    time.sleep(wait)
                else:
                    raise RuntimeError(
                        f"Veo poll/download failed after {_VEO_MAX_RETRIES + 1} attempts: {last_error}"
                    ) from last_error

    with trace_span("videogen", "generate_clip", session_id=session_id) as span:
        mp4_bytes, metadata = await asyncio.to_thread(_sync_generate)
        span["payload"].update(metadata)
        logger.info(
            "Veo generation completed in %.1fs (model=%s, submit_attempt=%d, download_attempt=%d)",
            metadata["latency_s"],
            _MODEL,
            metadata["submit_attempt"],
            metadata["download_attempt"],
        )
        return mp4_bytes, metadata
