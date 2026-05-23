"""Veo 3.1 video generation wrapper."""

import os
import time

from google import genai
from google.genai import types


def get_client() -> genai.Client:
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def safe_reference_image(
    image_bytes: bytes, mime: str = "image/png"
) -> types.VideoGenerationReferenceImage:
    """Build a reference image, working around SDK typing issue #1988."""
    img = types.Image(image_bytes=image_bytes, mime_type=mime)
    return types.VideoGenerationReferenceImage(
        image=img, reference_type="asset"
    )


def generate_whatif_clip(
    prompt_text: str,
    reference_frame_bytes: list[bytes],
    duration_s: int = 8,
    resolution: str = "720p",
    model: str = "veo-3.1-fast-generate-preview",
) -> tuple[bytes, dict]:
    """Submit Veo generation, poll, download. Returns (mp4_bytes, metadata)."""
    client = get_client()
    refs = [safe_reference_image(b) for b in reference_frame_bytes[:3]]

    operation = client.models.generate_videos(
        model=model,
        prompt=prompt_text,
        config=types.GenerateVideosConfig(
            reference_images=refs if refs else None,
            aspect_ratio="16:9",
            resolution=resolution,
        ),
    )

    started = time.time()
    while not operation.done:
        time.sleep(10 if time.time() - started < 30 else 5)
        operation = client.operations.get(operation)

    video = operation.response.generated_videos[0]
    video_file = client.files.download(file=video.video)
    mp4_bytes = video_file.read() if hasattr(video_file, "read") else video_file

    metadata = {
        "model": model,
        "duration_s": duration_s,
        "latency_s": time.time() - started,
    }
    return mp4_bytes, metadata
