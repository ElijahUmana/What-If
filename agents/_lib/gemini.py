"""Wrapper around google-genai for Gemini API calls."""

import json
import os

from google import genai
from google.genai import types

_client = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def caption_frame(image_bytes: bytes, system_prompt: str) -> dict:
    """Call gemini-3.1-flash-lite with an image for fast captioning."""
    client = get_client()
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite",
        contents=[
            types.Content(
                parts=[
                    types.Part(
                        inline_data=types.Blob(
                            data=image_bytes, mime_type="image/jpeg"
                        )
                    ),
                    types.Part(text=system_prompt),
                ]
            )
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    return json.loads(response.text)


def summarise_video(
    video_bytes: bytes, system_prompt: str, match_meta: dict
) -> dict:
    """Call gemini-3.5-flash with a video clip for deep summarisation."""
    client = get_client()
    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=[
            types.Content(
                parts=[
                    types.Part(
                        inline_data=types.Blob(
                            data=video_bytes, mime_type="video/mp4"
                        )
                    ),
                    types.Part(
                        text=system_prompt
                        + "\n\nMATCH_META: "
                        + json.dumps(match_meta)
                    ),
                ]
            )
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    return json.loads(response.text)


def embed_text(text: str) -> list[float]:
    """Generate embedding via text-embedding-004."""
    client = get_client()
    result = client.models.embed_content(
        model="text-embedding-004",
        content=text,
    )
    return result.embedding.values


def reason(
    system_prompt: str, user_prompt: str, model: str = "gemini-3.5-flash"
) -> dict:
    """General-purpose structured reasoning call."""
    client = get_client()
    response = client.models.generate_content(
        model=model,
        contents=[types.Content(parts=[types.Part(text=user_prompt)])],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            system_instruction=system_prompt,
            temperature=0.4,
        ),
    )
    return json.loads(response.text)
