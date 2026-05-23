# GMI Cloud — Deep Integration Specification

## Why GMI Cloud is load-bearing

This system has three jobs that GMI Cloud is uniquely well placed to carry:

1. **Heavy reasoning across many concurrent agents.** The DirectorAgent, MatchStateAgent, and RetrievalRerank step all run open-weight frontier-class reasoning models at high token volumes throughout a 90-minute session. GMI hosts DeepSeek V4 Pro (1M context), Kimi K2.6, and GLM-4.7/5 in serverless OpenAI-compatible endpoints at a fraction of what closed-vendor APIs charge — so the system can afford to run multiple reasoning calls per query.
2. **Deep visual continuity validation.** The ValidatorAgent's continuity check needs a serious vision-language model — not a small one. Qwen3-VL-235B (262K context, $0.30/$1.40 per 1M) on GMI is the strongest serverless VLM you can hit today.
3. **Custom workload on bare-metal NVIDIA infrastructure.** GMI's Cluster Engine + Python SDK lets us host an embedding model and a smaller fine-tunable VL captioner on dedicated H100/H200 endpoints — so the entire perception pipeline has a hot-swappable infrastructure path. This is the "deep" integration that goes beyond calling one model from a serverless catalog.

Pull GMI Cloud out and the system loses its primary reasoning brain, its continuity validator, and its bare-metal escape hatch.

## Canonical facts

- **Inference base URL:** `https://api.gmi-serving.com/v1`
- **Auth:** `Authorization: Bearer <GMI_API_KEY>`. Optional `X-Organization-ID: <org_id>` for multi-org accounts.
- **OpenAI compatibility:** Full. The `openai` Python SDK works as a drop-in via `base_url`.
- **JSON mode:** `response_format: {"type": "json_object"}` supported.
- **Tool calling:** Supported via standard `tools` parameter.
- **Streaming:** SSE, final chunk includes usage stats.
- **Console:** `https://console.gmicloud.ai` for keys + org.
- **Docs:** `https://docs.gmicloud.ai`
- **Python SDK (dedicated endpoints / cluster engine):** `pip install gmicloud`.
- **Rate-limit tiers:** Tier 1 free = 100K TPM. Tier 2 ($50 spent) = 2M TPM. Tier 5 ($10K) = 150M TPM. Tier upgrades take up to 24h after billed spend (vouchers don't count). Email `support@gmicloud.ai` for manual upgrade requests.
- **Hackathon credits:** Free GMI Cloud inference credits granted to all participants for the event we're shipping into. Ambassador program offers up to $300/mo for ongoing use.

## Model allocation — exactly what we use where

| Where | Model ID | Why this one | Volume |
|---|---|---|---|
| **DirectorAgent (counterfactual planning)** | `deepseek-ai/DeepSeek-V4-Pro` | 1M context, top reasoning, $1.74/$3.48 per 1M | ~10–20 calls/session (one per what-if + regens) |
| **DirectorAgent (fast path)** | `deepseek-ai/DeepSeek-V4-Flash` | Same family, ~12× cheaper, lower latency | Fast fallback when budget is tight |
| **MatchStateAgent (transition reasoning)** | `moonshotai/Kimi-K2.6` | 256K context, excellent structured output | One call per detected event (~30–60/session) |
| **RetrievalRerank** | `moonshotai/Kimi-K2.6` | Sharp on long-context rerank | One call per what-if (~10–20/session) |
| **ValidatorAgent (continuity check)** | `Qwen/Qwen3-VL-235B-A22B-Instruct-FP8` | 262K context VLM, multi-image input | One call per generation (~10–20/session) |
| **Captioner deep-pass on key frames** | `Qwen/Qwen3-VL-235B-A22B-Instruct-FP8` | Used only for highest-signal frames (scene transitions, detected events) | ~30–60 frames/session |
| **Custom embedding endpoint** | `BAAI/bge-m3` deployed to GMI dedicated H100 via `pip install gmicloud` | GMI does not have a serverless embeddings endpoint; we host our own | ~30k embeddings/session |
| **Match-meta extractor (one-shot)** | `zai-org/GLM-4.7` | Cheap ($0.40/$2.00 per 1M), good structured output | 1 call/session |
| **Audio commentary TTS** | `inworld-tts-1.5-max` | Native broadcast-grade voices, $0.01/request | Per commentary line that goes to audio (~150/session) |
| **Image generation fallback** | `seedream-5.0-lite` ($0.035/req) or `glm-image` ($0.01/req) | Fallback when Imagen isn't preferred | Rare |
| **Video generation alt path** | `wan2.6-i2v` ($0.15/req) or `sora-2-pro` ($0.50/req) | Stylistic variants for the Director's Cut compositor when we want a different look from Veo | Optional |

> **Note on serverless embeddings:** GMI does not publish a serverless `/v1/embeddings` endpoint. We host `BAAI/bge-m3` (or `bge-large-en-v1.5`) on a GMI dedicated endpoint with vLLM. Failing that path, we use Google's `text-embedding-004` via the Gemini API as a hot fallback — both options compiled into `agents/_lib/embeddings.py` behind a feature flag.

## High-QPS frame captioning — the right model

GMI's serverless VL catalog leads with `Qwen3-VL-235B` at flagship scale. Calling a 235B model at 2 fps would burn our rate-limit budget. So:

- **Primary captioner** runs on **Gemini 3.1 Flash Lite** via the Gemini API ($0.25/$1.50 per 1M, generous free tier, native multimodal). See `08_TECH_GEMINI_VEO.md`. This is the fast pass at 2 fps.
- **Deep-pass captioning** for key frames (scene transitions, events of interest) runs on **Qwen3-VL-235B on GMI** — fewer calls, richer output. This is where GMI's VL muscle adds real signal: detailed structured tags, multi-image cross-referencing, longer prompts.
- **Dedicated endpoint option:** for higher volume / lower latency, deploy `Qwen2.5-VL-7B-Instruct` on a GMI Cluster Engine H100 with vLLM. Latency ~150ms per call. Cost ~$2/hr while running — break-even vs the per-token serverless price at moderate session counts.

The integration is honest about both paths: free-tier Gemini handles the everyday volume; GMI's serious VL handles the everyday volume on dedicated hardware when we scale up; flagship Qwen3-VL on GMI's serverless handles the deep-pass frames.

## Calling shapes

### OpenAI SDK, streaming chat completion

```python
from openai import OpenAI

gmi = OpenAI(
    api_key=os.environ["GMI_API_KEY"],
    base_url="https://api.gmi-serving.com/v1",
)

def call_director(prompt: str) -> dict:
    response = gmi.chat.completions.create(
        model="deepseek-ai/DeepSeek-V4-Pro",
        messages=[
            {"role": "system", "content": open("prompts/director.system.md").read()},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=2048,
        temperature=0.4,
    )
    return json.loads(response.choices[0].message.content)
```

### Vision call with image_url (Qwen3-VL)

```python
def deep_caption(frame_jpeg_b64: str, prior_caption: str) -> dict:
    response = gmi.chat.completions.create(
        model="Qwen/Qwen3-VL-235B-A22B-Instruct-FP8",
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_jpeg_b64}"}},
                {"type": "text", "text": (
                    "Football broadcast frame. Provide a detailed structured description: "
                    "player positions by jersey number, ball location, action, scene type. "
                    "Prior frame caption for context: " + prior_caption +
                    "\nReturn JSON only."
                )},
            ],
        }],
        response_format={"type": "json_object"},
        max_tokens=512,
        temperature=0.1,
    )
    return json.loads(response.choices[0].message.content)
```

### Validator continuity check (multi-image into Qwen3-VL-235B)

```python
def validate_continuity(reference_frames_b64: list[str], sampled_clip_frames_b64: list[str], brief_continuity: dict) -> dict:
    image_blocks = []
    for b in reference_frames_b64:
        image_blocks.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}})
    for b in sampled_clip_frames_b64:
        image_blocks.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}})

    response = gmi.chat.completions.create(
        model="Qwen/Qwen3-VL-235B-A22B-Instruct-FP8",
        messages=[{
            "role": "user",
            "content": image_blocks + [
                {"type": "text", "text": open("prompts/validator.continuity.md").read()},
                {"type": "text", "text": "CONTINUITY_BRIEF:\n" + json.dumps(brief_continuity)},
                {"type": "text", "text": (
                    f"REFERENCE_FRAMES: indices 0..{len(reference_frames_b64)-1}.  "
                    f"SAMPLED_FRAMES_FROM_CLIP: indices {len(reference_frames_b64)}..{len(reference_frames_b64)+len(sampled_clip_frames_b64)-1}."
                )},
            ],
        }],
        response_format={"type": "json_object"},
        max_tokens=1024,
        temperature=0.0,
    )
    return json.loads(response.choices[0].message.content)
```

### Dedicated endpoint deploy (BGE-M3 for embeddings)

```python
# scripts/deploy/bge_m3_endpoint.py
from gmicloud import Client

client = Client()  # uses GMI_CLOUD_CLIENT_ID, EMAIL, PASSWORD env vars

templates = client.list_templates()
vllm_tpl = next(t for t in templates if t.name == "vllm-openai-compatible")

artifact_id, resources = client.create_artifact_from_template(
    vllm_tpl,
    overrides={
        "model_id": "BAAI/bge-m3",
        "served_model_name": "bge-m3",
        "tensor_parallel_size": 1,
        "gpu_memory_utilization": 0.8,
        "max_model_len": 8192,
    },
)

task_id = client.create_task(
    artifact_id,
    resources={"gpu_type": "H100", "gpu_count": 1, "region": "us-denver-1"},
    scheduling_config={"min_replicas": 1, "max_replicas": 2, "scale_to_zero_idle_s": 600},
)
client.start_task_and_wait(task_id)

endpoint_url = client.get_endpoint(task_id).url
print(f"Embedding endpoint live at: {endpoint_url}/v1/embeddings")
```

The dedicated endpoint exposes an OpenAI-compatible `/v1/embeddings` interface, so the rest of the codebase calls it the same way it would call OpenAI.

### TypeScript client (Vercel AI SDK provider)

```typescript
import { generateText, streamText } from 'ai';
import { gmicloud } from '@gmicloud/ai-sdk-provider';

const result = await streamText({
  model: gmicloud('deepseek-ai/DeepSeek-V4-Pro'),
  prompt: 'Compose a Veo brief...',
});
```

The TS frontend never calls GMI directly — it goes through the session gateway — but the SDK is here for any Node-side tools we build.

## Custom workload via Cluster Engine

GMI's bare-metal Cluster Engine matters for two non-cosmetic uses:

1. **Embedding endpoint** as above — required because there is no serverless embeddings endpoint.
2. **Smaller VL captioner on H100** for high-QPS captioning at low cost — `Qwen2.5-VL-7B-Instruct` via vLLM. Reserved for production scale; not required to launch.

Both are managed by the `gmicloud` Python SDK in `infra/dedicated_endpoints/`. The Terraform module wires their endpoints into the gateway's environment so the agents transparently route to dedicated instances when configured, and fall back to serverless / Google APIs when not.

## Rate-limit strategy

Tier 1's 100K TPM cap is tight for a session with bursty agentic calls. Plan:

- **Charge $50 to the team account immediately at hackathon kickoff** to unlock Tier 2 (2M TPM standard / 450K TPM DeepSeek R/V3-Base).
- **Email `support@gmicloud.ai`** at the same time to request a hackathon-bounded upgrade to Tier 3 or higher.
- **Throughput separation:** Director / Match-state / Retrieval calls are bursty — they don't need sustained QPS, so they fit Tier 2 easily. Validator continuity calls also bursty.
- **Daily budget guardrail in code:** the gateway tracks per-session GMI token usage. When a session passes a configured ceiling, the captioner deep-pass is suspended and routed to Gemini-only — degraded mode rather than failure mode.

## Token / cost envelope per match

| Component | Calls | Tokens estimate | $ estimate |
|---|---|---|---|
| Director — DeepSeek V4 Pro | 20 (whatifs + regens) | 30k in / 5k out per call | ~$1.50 |
| Match state — Kimi K2.6 | 60 | 4k in / 300 out per call | ~$0.30 |
| Retrieval rerank — Kimi K2.6 | 20 | 12k in / 500 out per call | ~$0.40 |
| Validator continuity — Qwen3-VL-235B | 20 | 30k in / 1k out per call (multi-image) | ~$0.20 |
| Deep-pass caption — Qwen3-VL-235B | 60 | 5k in / 200 out per call | ~$0.10 |
| TTS — Inworld TTS 1.5 Max | 150 | ~$1.50 |
| **Per match** | | | **~$4 / session** |

GMI's economics make it ~3× cheaper than running the same load on closed-vendor APIs.

## Provenance

Every GMI call lands in our `trace_event` table as a `model_call` span with:
- `model_id` — the exact ID we sent.
- `input_ref` — blob containing the full message list (with image URIs but not raw bytes).
- `output_ref` — blob containing the full response.
- `latency_ms` — measured client-side.
- `payload.token_usage` — from the SSE final chunk.
- `payload.tier_state` — the current per-session GMI token budget remaining.

These flow into the trace explorer like any other model call. Replay is straightforward: the trace contains everything needed to re-issue the call.

## Why this is deep integration

- **Three distinct model families** (DeepSeek, Kimi, Qwen-VL) used in three different roles where each is the right answer.
- **Custom dedicated endpoint** deployed via the official Python SDK, hosting our own BGE-M3 in GMI's cluster — going beyond the catalog.
- **OpenAI compatibility used as a foundation, not a gimmick** — the architecture is provider-portable but we use GMI's specific models because nothing else has the cost + capability profile we need.
- **TTS for actual broadcast voice** — using Inworld via GMI for the user-facing commentary audio path.
- **Provenance-grade tracing** of every call.

Pull GMI Cloud out and you replace three load-bearing models, host your own embedding endpoint somewhere else, and lose the bare-metal escape hatch. There is no shallow story here.
