"""GMI Cloud client — OpenAI-compatible inference on DeepSeek V4 Flash."""
import os
import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

_client: OpenAI | None = None

def get_client() -> OpenAI:
    global _client
    if _client is None:
        key = os.environ.get("GMI_API_KEY", "")
        if not key:
            raise RuntimeError("GMI_API_KEY not set")
        _client = OpenAI(api_key=key, base_url="https://api.gmi-serving.com/v1")
    return _client

def reason(system_prompt: str, user_prompt: str, model: str = "deepseek-ai/DeepSeek-V4-Flash") -> dict:
    """Structured JSON reasoning via GMI Cloud."""
    client = get_client()
    # DeepSeek requires "json" in messages for json_object response format
    if "json" not in user_prompt.lower() and "json" not in system_prompt.lower():
        user_prompt += "\n\nRespond in JSON format."
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=4096,
        temperature=0.4,
    )
    content = response.choices[0].message.content
    return json.loads(content)

def chat(system_prompt: str, user_prompt: str, model: str = "deepseek-ai/DeepSeek-V4-Flash") -> str:
    """Plain text chat via GMI Cloud."""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=2048,
        temperature=0.7,
    )
    return response.choices[0].message.content
