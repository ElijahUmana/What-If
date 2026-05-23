"""GMI Cloud wrapper (OpenAI-compatible).

NOTE: the GMI key is not yet available so this uses a fallback to Gemini for now.
"""

import json
import os

from openai import OpenAI


def get_client() -> OpenAI | None:
    key = os.environ.get("GMI_API_KEY", "")
    if not key or key == "GMICUP10":
        # Fallback: use Gemini for reasoning tasks until GMI key arrives
        return None
    return OpenAI(api_key=key, base_url="https://api.gmi-serving.com/v1")


def reason_gmi(
    system_prompt: str,
    user_prompt: str,
    model: str = "deepseek-ai/DeepSeek-V4-Pro",
) -> dict:
    client = get_client()
    if client is None:
        from . import gemini

        return gemini.reason(system_prompt, user_prompt)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=2048,
        temperature=0.4,
    )
    return json.loads(response.choices[0].message.content)


def vision_gmi(
    image_b64: str,
    prompt: str,
    model: str = "Qwen/Qwen3-VL-235B-A22B-Instruct-FP8",
) -> dict:
    client = get_client()
    if client is None:
        return {}  # GMI not available yet; caller should fall back

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        response_format={"type": "json_object"},
        max_tokens=512,
        temperature=0.1,
    )
    return json.loads(response.choices[0].message.content)
