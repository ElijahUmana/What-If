# Google AI — Gemini + Veo + Live + Imagen Deep Integration Specification

## Why Google AI is load-bearing

Three different Google capabilities carry three different parts of the system:

- **Gemini 3.5 Flash** — deep video understanding for the summariser and the validator. The only off-the-shelf model that accepts video natively with a 1M-token context window in a stable GA release.
- **Gemini Live (gemini-3.1-flash-live-preview)** — the conversational broadcast voice. Real-time bidirectional WebSocket streaming with audio out.
- **Veo 3.1** — the counterfactual generator. The reference-image conditioning, native sync audio, and 8-second clip output with optional chaining are exactly what the system needs.

Plus **Imagen 4 Fast** for the share-page OG poster generation, and **Nano Banana 2** (`gemini-3.1-flash-image-preview`) for storyboard frames when Veo needs character-consistent inputs.

Pulling any one of these out replaces a model whose precise capability we depend on with no equivalent on any other provider today.

## Models we use and where

| Where in the system | Model ID | Why this specific one |
|---|---|---|
| SummariserAgent | `gemini-3.5-flash` | 1M context, video input, GA stable, free tier unlimited at reduced QPS, YouTube URL support for archive ingestion. |
| DirectorAgent | `gemini-3.5-flash` (low-latency reasoning) with optional `gemini-3.1-pro-preview` for complex prompts | Pro for the deepest counterfactual reasoning, Flash for everything else. |
| ValidatorAgent (fidelity check) | `gemini-3.5-flash` (with the generated MP4 as input) | Video-in capability used here in a way no other model offers. |
| CommentaryAgent | `gemini-3.1-flash-live-preview` (Live API) | Audio output streaming, sub-second latency, real-time broadcast voice. |
| VideoGenAgent (primary) | `veo-3.1-generate-preview` | Reference image conditioning, native audio, 8s @ 720p/1080p. |
| VideoGenAgent (fast fallback) | `veo-3.1-fast-generate-preview` | When latency budget is tight, 30–45s generation. |
| VideoGenAgent (budget) | `veo-3.1-lite-generate-preview` | $0.03–0.05/sec for high-volume what-ifs. |
| Storyboard helper | `gemini-3.1-flash-image-preview` (Nano Banana 2) | When Veo needs a character-consistent reference image we don't have a frame for. |
| Share-page OG poster | `imagen-4.0-fast-generate-001` | One-shot share-card generation. |
| Optional ambience music | `lyria-3-clip-preview` | Optional 30s music bed for the share-page hero. |

## Auth and SDK

- **Single SDK:** `pip install google-genai` (Python) or `npm i @google/genai` (TS). Same SDK covers Gemini + Veo + Imagen + Live + Lyria.
- **API key:** `GEMINI_API_KEY` from `https://aistudio.google.com/apikey`. We restrict the key to our service principal IPs (required after 2026-06-19).
- **Project mode:** AI Studio for everything in this system. Vertex AI not required (simpler auth, same models, same pricing).
- **Tiers:** We start on free tier for dev. Production uses paid tier; opt out of training data use is automatic on paid tier.

## SummariserAgent integration

### Per-window call (every 30 s)

```python
from google import genai
from google.genai import types
import json

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

def summarise_window(window_clip_uri: str, match_meta: dict, frame_uris: list[str]) -> dict:
    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=[
            types.Content(parts=[
                types.Part(file_data=types.FileData(file_uri=window_clip_uri)),
                types.Part(text=build_summariser_prompt(match_meta)),
            ]),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SUMMARISER_SCHEMA,
            system_instruction=open("prompts/summariser.system.md").read(),
            temperature=0.2,
        ),
    )
    return json.loads(response.text)
```

Notes:
- `response_mime_type="application/json"` + `response_schema=...` gives us structured output enforced by the model.
- `file_uri` can be a GCS URI (we upload the concatenated window MP4 first) or a YouTube URL for offline backfill.
- We set `temperature=0.2` because we want repeatable, factual descriptions.

### Auto-expand on low confidence

The summariser's `self_critique.should_expand_window` triggers a wider concatenation and a re-call. Up to two expansions (30 s → 60 s → 90 s). Beyond that, accept the lower-confidence result and log it.

### Cost control

- Cache repeated context (match metadata, persona prompt) using Gemini's prompt cache feature: `cache_id` parameter on `GenerateContentConfig`.
- Free tier: 15 RPM / 1500 RPD with reduced quality knobs — sufficient for early development.
- Paid tier: $1.50 input / $9.00 output per 1M tokens. A 30-second window at low-res sampling is ~3000 tokens input + ~500 tokens output ≈ $0.009/window ≈ $1.62/match.

## DirectorAgent integration

### Composing the Veo brief

```python
def compose_veo_brief(
    user_prompt: str,
    anchor_event: dict,
    window_frames: list[str],
    window_captions: list[str],
    window_summary: dict,
    match_state: dict,
    validator_feedback: dict | None,
) -> dict:
    parts = [
        types.Part(text=open("prompts/director.system.md").read()),
        types.Part(text=f"USER_PROMPT: {user_prompt}"),
        types.Part(text=f"ANCHOR_EVENT: {json.dumps(anchor_event)}"),
        types.Part(text=f"WINDOW_CAPTIONS: {json.dumps(window_captions)}"),
        types.Part(text=f"WINDOW_SUMMARY: {json.dumps(window_summary)}"),
        types.Part(text=f"MATCH_STATE: {json.dumps(match_state)}"),
    ]
    if validator_feedback:
        parts.append(types.Part(text=f"VALIDATOR_FEEDBACK: {json.dumps(validator_feedback)}"))
    for uri in window_frames:
        parts.append(types.Part(file_data=types.FileData(file_uri=uri)))

    response = client.models.generate_content(
        model="gemini-3.5-flash",  # use 3.1-pro-preview for high-difficulty prompts
        contents=[types.Content(parts=parts)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VEO_BRIEF_SCHEMA,
            temperature=0.4,
        ),
    )
    return json.loads(response.text)
```

The director's output is itself a structured Veo brief (schema in `prompts/director.veo_schema.md`) — not a Gemini-flavoured string.

## VideoGenAgent integration

### Submitting Veo with reference frames

```python
import time
from google.genai import types

def generate_whatif_clip(brief: dict, reference_frame_uris: list[str]) -> dict:
    reference_images = []
    for uri in reference_frame_uris:
        img_bytes = storage.download(uri)
        reference_images.append(
            types.VideoGenerationReferenceImage(
                image=types.Image(image_bytes=img_bytes, mime_type="image/jpeg"),
                reference_type="asset",
            )
        )

    prompt_text = build_natural_language_veo_prompt(brief)

    operation = client.models.generate_videos(
        model="veo-3.1-generate-preview",
        prompt=prompt_text,
        config=types.GenerateVideosConfig(
            reference_images=reference_images[:3],   # Veo accepts up to 3 reference images
            aspect_ratio="16:9",
            resolution="720p",
            duration_seconds=brief["model_params"]["duration_s"],
        ),
    )

    started = time.time()
    while not operation.done:
        time.sleep(10 if time.time() - started < 30 else 5)
        operation = client.operations.get(operation)

    video = operation.response.generated_videos[0]
    out_path = f"/tmp/{uuid4()}.mp4"
    client.files.download(file=video.video).save(out_path)
    return {"path": out_path, "duration_s": brief["model_params"]["duration_s"]}


def build_natural_language_veo_prompt(brief: dict) -> str:
    """Convert the structured brief into the 1024-token natural-language prompt Veo accepts."""
    sections = [
        f"SCENE: {brief['scene']['stadium']}, {brief['scene']['lighting']}, {brief['scene']['weather']}, {brief['scene']['crowd_density']} crowd.",
        f"CONTINUITY: {brief['continuity']['home']['name']} in {brief['continuity']['home']['kit_color_primary']}; {brief['continuity']['away']['name']} in {brief['continuity']['away']['kit_color_primary']}; goalkeepers as referenced.",
        f"WHAT ACTUALLY HAPPENED (DO NOT show this): {brief['real_event']['description']}",
        f"WHAT IF (DO show this): {brief['counterfactual_delta']['beat_description']}",
        "CONTINUATION:",
    ]
    for i, beat in enumerate(brief["continuation_beats"], 1):
        sections.append(f"  beat {i} (~{beat['duration_s']}s): {beat['description']}")
    sections.append(f"AUDIO: crowd — {brief['audio']['crowd']}; ambient — {brief['audio']['ambient']}.")
    if brief['audio'].get('broadcaster_voiceover'):
        sections.append(f"BROADCASTER: {brief['audio']['broadcaster_voiceover']}")
    sections.append(f"CAMERA: {brief['camera']['persona']}, {brief['camera']['movement']}, no graphical overlays.")
    sections.append("AVOID: " + "; ".join(brief["negative"]))
    return "\n".join(sections)
```

Notes:
- Veo's prompt is capped at 1024 tokens — the natural-language flattener above stays well within.
- We use up to **3 reference images** (Veo 3.1's max) chosen by the director to lock camera angle, player appearance, stadium look.
- We default to **720p** to keep latency tight; switch to 1080p for the final Director's Cut composition.
- We persist the LRO operation ID in `generation.metadata` so we can replay/inspect.

### Generation budgets

| Model | Latency (8s clip @ 720p) | Cost |
|---|---|---|
| `veo-3.1-fast-generate-preview` | 30–45 s | ~$0.80–1.20 |
| `veo-3.1-lite-generate-preview` | 60–90 s | ~$0.24–0.40 |
| `veo-3.1-generate-preview` | 90–180 s | ~$3.20 |

Default model: `veo-3.1-fast-generate-preview` for live what-ifs. Upgrade to standard for the Director's Cut's final clip if time allows.

### Video extension (for chained narratives)

When a what-if branches from a previous what-if, we use Veo's video extension feature (up to 20 × 7 s extensions at 720p) so the branched clip continues plausibly from the original. The video_extension parameter takes the parent clip's MP4 as input.

### SDK caveat

There is a known issue in `google-genai` Python SDK (GitHub googleapis/python-genai#1988) with the typing of `VideoGenerationReferenceImage`. Pin to the latest minor version and patch if needed. Tracking in `agents/_lib/veo.py` — we have a small `safe_reference_image()` builder that bypasses the typing issue.

## ValidatorAgent integration (Gemini side)

### Fidelity check — model watches the generated clip

```python
def validate_fidelity(clip_uri: str, user_prompt: str, real_event: dict, counterfactual: dict) -> dict:
    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=[
            types.Content(parts=[
                types.Part(file_data=types.FileData(file_uri=clip_uri)),
                types.Part(text=open("prompts/validator.fidelity.md").read()),
                types.Part(text=f"USER_PROMPT: {user_prompt}"),
                types.Part(text=f"REAL_EVENT: {json.dumps(real_event)}"),
                types.Part(text=f"COUNTERFACTUAL_DELTA: {json.dumps(counterfactual)}"),
            ]),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=FIDELITY_VERDICT_SCHEMA,
            temperature=0.0,
        ),
    )
    return json.loads(response.text)
```

This is the load-bearing use of Gemini's video-in: we hand the model the actual generated MP4 and ask it to judge whether the counterfactual occurred. No frame-by-frame fallback needed.

## CommentaryAgent integration (Gemini Live)

### Persistent WS session

```python
import asyncio
from google import genai
from google.genai import types

async def run_commentary_session(session_id: str, bus: AsyncIterator[dict], outbound: Queue):
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    config = {
        "response_modalities": ["AUDIO"],  # audio out
        "output_audio_transcription": {},  # also get text transcription
        "system_instruction": {"parts": [{"text": open("prompts/commentary.persona.md").read()}]},
    }
    async with client.aio.live.connect(
        model="gemini-3.1-flash-live-preview",
        config=config,
    ) as live:
        # rotate every ~110s to avoid the 2-min audio+video cap
        rotate_at = asyncio.get_event_loop().time() + 110
        async for event in bus:
            if asyncio.get_event_loop().time() > rotate_at:
                break  # outer loop will reconnect
            if event["kind"] == "summary.created":
                await live.send_realtime_input(text=f"summary:{json.dumps(event['payload'])}")
            elif event["kind"] == "event.created":
                await live.send_realtime_input(text=f"event:{json.dumps(event['payload'])}")
            elif event["kind"] == "match_state.update":
                await live.send_realtime_input(text=f"state:{json.dumps(event['payload'])}")
            async for response in live.receive():
                if response.server_content and response.server_content.output_transcription:
                    outbound.put_nowait({"type": "commentary.line", "text": response.server_content.output_transcription.text})
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        if part.inline_data:
                            outbound.put_nowait({"type": "commentary.audio", "audio_b64": base64.b64encode(part.inline_data.data).decode()})
```

Notes:
- The 2-minute audio+video cap forces session rotation. We use **audio-only + structured text in** (no video frames sent live) which gives us the **15-minute cap** instead — perfectly fine for the 30-second event cadence and 110-second rotation is conservative.
- Audio output is streamed to the frontend as 24kHz PCM; the frontend plays it directly. Text transcription doubles as the visible commentary feed.

## Imagen 4 + Nano Banana usage

### Imagen 4 Fast — share-page OG poster

```python
img = client.models.generate_images(
    model="imagen-4.0-fast-generate-001",
    prompt=f"Match poster, {match_meta['home_team']} vs {match_meta['away_team']}, dramatic stadium lighting, broadcast aesthetic, kit colours {home_kit} and {away_kit}, no text",
    config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="16:9"),
)
poster_bytes = img.generated_images[0].image.image_bytes
```

### Nano Banana 2 — character-consistent storyboard frame (fallback for Veo reference)

When the user's what-if references a player who is currently off-camera (e.g. "what if the bench striker had come on?"), we don't have a recent reference frame of them. We use Nano Banana 2 with multiple older reference frames of that player to produce a character-consistent storyboard frame to feed Veo.

```python
storyboard = client.models.generate_images(
    model="gemini-3.1-flash-image-preview",
    prompt=f"Football player in {team_kit_color} jersey, number {jersey_number}, standing on the pitch ready to come on as a substitute, broadcast-style framing",
    config=types.GenerateImagesConfig(
        number_of_images=1,
        reference_images=[ref1, ref2, ref3],  # older frames of this player
    ),
)
```

This is the recommended pipeline per Google's documentation: Nano Banana 2 for character/scene consistency → Veo 3.1 for video.

## Lyria 3 — optional share-page music bed

The shareable Director's Cut page can play a 30-second background music bed on the hero. Lyria 3 Clip:

```python
clip = client.models.generate_music(
    model="lyria-3-clip-preview",
    prompt="Epic football match anthem, ambient, no lyrics, builds to a crescendo, dramatic strings, broadcast intro feel",
    config={"duration_seconds": 30},
)
```

Skip this if cost matters; it is not on the critical path.

## Constraints we plan around

1. **No live HLS into Gemini.** We capture frames ourselves and feed them as `image_url` or upload chunks to GCS first.
2. **Veo latency is 30–180s.** This is in the latency budget in `02_ARCHITECTURE.md`. The UI surfaces progress; the live match keeps playing.
3. **Veo outputs 8s max.** Chained extensions allow up to ~148s for longer narratives.
4. **SynthID is non-optional.** All generated content carries the watermark. We preserve it; we also add our own visible "What If" wordmark.
5. **API key restrictions** after 2026-06-19. Configured in AI Studio.
6. **Audio+video Live sessions cap at 2 minutes.** Mitigated by audio-only + structured text input (15-minute cap) and 110-second rotation.
7. **Free tier may train on data.** We use paid tier in production.
8. **Veo SDK reference-image typing bug.** Patched in `agents/_lib/veo.py`.

## Cost envelope per match (estimated)

| Component | Cost |
|---|---|
| Summariser (180 windows × ~$0.009) | ~$1.62 |
| Live commentary (90 min audio out @ ~$0.018/min) | ~$1.62 |
| Director + validator (10 what-ifs × ~$0.05) | ~$0.50 |
| Veo (10 what-ifs × ~$0.80 at Fast 720p) | ~$8.00 |
| Imagen 4 OG poster (1) | ~$0.02 |
| **Per match total** | **~$12 / session** |

Cheap enough to support a free tier with daily limits, and modest enough to be funded by a single $20 user subscription per month at 1–2 matches per week.
