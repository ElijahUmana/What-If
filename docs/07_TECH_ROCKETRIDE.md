# RocketRide — Deep Integration Specification

## Why RocketRide is load-bearing in this system

RocketRide is **not** a thin LLM wrapper — it is a stateful pipeline runtime with a C++ execution engine, a 50+ node Python ecosystem, and visual IDE tooling. This system is exactly the kind of long-lived multi-tier workload RocketRide was designed for: a directed graph of nodes that runs for the duration of a 90-minute match, fanning frames out to perception nodes, fanning summaries into a wave-planning agent, fanning generation back through validation. We use RocketRide as our **primary runtime substrate**, not as an afterthought.

Pull RocketRide out and there is no orchestration left.

## Canonical facts

- **Engine:** C++ multithreaded execution engine, default port `localhost:5565`, exposes Debug Adapter Protocol over WebSocket.
- **Node ecosystem:** Python, declarative `services.json` manifests, 50+ built-in nodes.
- **IDE extension:** VS Code / Cursor / Windsurf — `RocketRide.rocketride` on the marketplace, version 1.1.0+. Provides drag-and-drop `.pipe` canvas + local engine subprocess manager + real-time execution trace.
- **License:** MIT (Aparavi Software AG copyright).
- **Repos we depend on:**
  - `github.com/rocketride-org/rocketride-server` — engine + nodes (v3.2.0 as of 2026-05-22).
  - `github.com/rocketride-org/rocketride-workshops` — example pipelines.
- **SDKs:**
  - `pip install rocketride` (Python client, v1.1.0+).
  - `npm install rocketride` (TypeScript client, v1.1.0+).
  - `pip install rocketride-mcp` (MCP server bridge — relevant for plugging Claude into our pipeline).
- **Deployment:**
  - Docker image: `ghcr.io/rocketride-org/rocketride-engine:latest`.
  - Helm charts in `deploy/helm/`.
  - Single engine per box; pipelines run as tasks within the long-lived engine process.

## How we use RocketRide

### Pipelines we ship (`agents/pipelines/`)

Each pipeline below is a `.pipe` JSON file. The engine loads them at startup; the EaaS WebSocket proxy fans connections in.

#### 1. `perception.pipe` — the always-on perception pipeline

One pipeline per active session. Long-running for the lifetime of the match.

Node graph (left to right = data flow):
```
youtube_ingest (custom node) ──► frame_grabber (interval=0.5s) ──► llm_vision_gmi_cloud (captioner) ──► memory_persistent (timeline_index)
                              ╲                                  ╲
                               ╲                                  ╲──► embedding_gmi (caption_embedding)
                                ╲
                                 ╲──► chunk_writer (custom node) ──► tool_pipe(window_summariser_pipe)
                                                                   ╲
                                                                    ╲──► event_emitter (custom node)
                                                                              ╲
                                                                               ╲──► agent_rocketride (match_state_agent) ──► memory_persistent
                                                                                       ╲
                                                                                        ╲──► llm_gemini_live (commentary_stream)
```

Key node-level decisions:
- **`youtube_ingest`** — our custom node wrapping yt-dlp + ffmpeg (RocketRide doesn't ship YouTube live ingest natively; we add it to `nodes/src/nodes/youtube_ingest/` with a `services.json` manifest).
- **`frame_grabber`** — built-in node, configured to `interval` mode at 0.5 s (2 fps). Outputs `image` lane and `documents` lane (preserves frame number + timestamp).
- **`llm_vision_gmi_cloud`** — we use the `llm_vision_openai` node with `base_url` overridden to GMI Cloud's OpenAI-compatible endpoint (see `06_TECH_GMI_CLOUD.md`). RocketRide has a built-in `llm_gmi_cloud` node but it lacks vision — so we use `llm_openai_api` configured for GMI's `Qwen2.5-VL` model with vision content blocks.
- **`memory_persistent`** — Redis-backed cross-session memory; stores the timeline index keyed by `pts_ms`.
- **`tool_pipe(window_summariser_pipe)`** — exposes the summariser sub-pipeline as a tool to the wave agent, so the orchestrator can request "summarise this window with custom parameters" on demand.

#### 2. `window_summariser.pipe` — the 30-second window summariser

Triggered every 30 s of source time by a timer node.

```
window_trigger ──► chunk_concat (ffmpeg) ──► llm_vision_gemini (gemini-3.5-flash, video input) ──► event_parser ──► memory_persistent
                                          ╲
                                           ╲──► self_critique_router
                                                  ╲
                                                   ╲──► (if expand): chunk_concat (wider window) ──► (loop back)
```

- **`llm_vision_gemini`** — built-in node, configured for `gemini-3.5-flash` with native video input. Supports our 30 s window + auto-expand to 60 s / 90 s.
- **`event_parser`** — small Python node that validates the structured output against our schema and emits `event.created` to the bus.

#### 3. `whatif.pipe` — the counterfactual generation pipeline

Triggered per user query.

```
query_input ──► agent_rocketride (director_agent, max_waves=8) ──► response_clip
                          │ control plane (tools):
                          ├─ tool_pipe(retrieval_pipe)
                          ├─ tool_pipe(reference_frames_pipe)
                          ├─ tool_pipe(veo_generation_pipe)
                          └─ tool_pipe(validator_pipe)
```

The director is an `agent_rocketride` with `max_waves=8`. Its instructions tell it:
1. First wave: call the retrieval tool, then the reference-frames tool.
2. Second wave: compose the Veo brief in structured JSON.
3. Third wave: call the Veo generation tool.
4. Fourth wave: call the validator.
5. If validator says `regenerate`, return to wave 2 with the feedback incorporated.
6. If validator says `ok` or `reject`, return.

Each tool is a sub-pipeline exposed via `tool_pipe`, which means the director sees them as callable tools but the engine treats them as full pipeline executions with their own traces.

#### 4. `retrieval.pipe` — anchor resolution

```
query_input ──► query_parser (regex for timestamps) ──► embedding_gmi (query_embedding)
                                                    ╲
                                                     ╲──► tool_filesystem (pgvector_search via custom node)
                                                            ╲
                                                             ╲──► llm_gemini (gemini-3.5-flash rerank) ──► clarification_router
```

#### 5. `veo_generation.pipe` — Veo wrapper

```
brief_input ──► reference_image_loader (loads keyframes from GCS)
            ╲
             ╲──► llm_video_veo (custom node wrapping client.models.generate_videos)
                                          │
                                          ▼
                                      poll_loop (every 10s)
                                          │
                                          ▼
                                      file_download (GCS upload)
```

`llm_video_veo` is our custom node. It uses the Gemini API SDK (`google-genai`) with `model="veo-3.1-generate-preview"` and `reference_images=[...]`. Polling is handled inside the node so the agent sees one synchronous tool call.

#### 6. `validator.pipe` — fan-out validation

```
clip_input ──┬──► llm_vision_gemini (fidelity check, gemini-3.5-flash)
             └──► llm_vision_gmi (continuity check, Qwen2.5-VL on GMI)
                                       │
                                       ▼
                              verdict_merger (Python node) ──► verdict_output
```

### Agents we author

We use `agent_rocketride` (the "Wave" agent) for orchestration where wave-planning fits, and we use `agent_crewai` only where a specialised single-purpose persona is the right unit. We do **not** use `agent_langchain` — wave-planning + tool-as-pipeline composition is a cleaner match for this workload.

| Logical agent | RocketRide implementation |
|---|---|
| IngestAgent | Sub-pipeline driven by our `youtube_ingest` custom node — not an `agent_*`. |
| FrameCaptionerAgent | A `llm_vision_*` node, called from `perception.pipe`. |
| SummariserAgent | A `llm_vision_gemini` node, called from `window_summariser.pipe`. |
| MatchStateAgent | `agent_rocketride` with `max_waves=3`, tools: `tool_python` (state transition), `memory_persistent`. |
| CommentaryAgent | A `llm_gemini_live` node (using Gemini Live with `gemini-3.1-flash-live-preview`). |
| RetrievalAgent | Sub-pipeline `retrieval.pipe`. |
| DirectorAgent | `agent_rocketride` with `max_waves=8`, tools listed above. |
| VideoGenAgent | Our `llm_video_veo` custom node in `veo_generation.pipe`. |
| ValidatorAgent | Sub-pipeline `validator.pipe`. |
| CompositorAgent | A `tool_python` node calling our ffmpeg helper. |
| SessionAgent | A control pipeline `session.pipe` triggered by WebSocket events. |
| TraceAgent | We hook into RocketRide's native execution trace via the event API + write to our `trace_event` table; no separate agent_rocketride node needed. |

### Custom nodes we add to the ecosystem

These are nontrivial and load-bearing. Each is a contribution to the open-source RocketRide node ecosystem; we open PRs upstream as part of the project.

1. **`youtube_ingest`** — pulls a live YouTube manifest via yt-dlp, runs ffmpeg as a subprocess, emits chunks + frames + metadata as RocketRide events.
   - Manifest: `nodes/src/nodes/youtube_ingest/services.json`.
   - Implementation: `nodes/src/nodes/youtube_ingest/main.py`.
   - Outputs: `chunks` lane (binary), `frames` lane (image + metadata).
   - Configurable: `fps`, `chunk_seconds`, `resolution`, `quality`.

2. **`llm_video_veo`** — wraps the Veo 3.1 video generation API.
   - Inputs: `brief` lane (structured JSON), `reference_images` lane (image array).
   - Outputs: `video` lane (binary), `metadata` lane (operation ID, duration, latency).
   - Handles polling, errors, SDK reference-image typing workaround.

3. **`pgvector_search`** — pgvector kNN query node.
   - Inputs: `embedding` lane (vector), `filter` lane (JSON), `top_k` config.
   - Outputs: `results` lane (rows + similarity scores).

4. **`ffmpeg_compose`** — programmatic ffmpeg invocation for the compositor.
   - Inputs: `clips` lane (array of MP4 URIs), `branch_cards` lane (PNG URIs).
   - Outputs: `composed` lane (MP4 URI), `hls_manifest` lane (M3U8 URI).

5. **`websocket_session_input`** — receives user actions from the session gateway over WS.
   - Inputs: WebSocket from gateway.
   - Outputs: `events` lane (typed WS frames).

### Memory model

- **`memory_persistent`** keyed `timeline_index` per session — stores caption / summary / event refs with embeddings (the actual vectors live in pgvector; this memory stores the IDs and structured metadata).
- **`memory_persistent`** keyed `match_state` per session — current state JSON, updated by MatchStateAgent.
- **`memory_internal`** per pipeline execution — the wave-agent scratch and per-wave intermediate results.

### Engine deployment

- **Local dev:** The VS Code extension launches a local engine on `localhost:5565`. We open `.pipe` files in the canvas to debug.
- **Production:** A single engine container per region. `docker run -p 5565:5565 ghcr.io/rocketride-org/rocketride-engine:latest`. Pipelines mounted at `/pipelines`. Resource sizing per `13_INFRA.md`.
- **Scaling:** Horizontal — multiple engine pods behind a session-affinity router. The gateway pins a session to one engine.

### Observability we get for free

- Per-node token usage, latency, memory stats — surfaced in the VS Code execution trace.
- Event stream over WS (`apaevt_status_*` events) — we wire this into our `trace_event` writer.

### Observability we add

- Every node emits a span to our trace store via a small wrapper around the RocketRide event stream — converts RocketRide native events into the `trace_event` schema in `03_DATA_MODEL.md`.
- This is why the trace explorer can show a unified view: RocketRide native trace + our domain trace, joined by span IDs.

### Why this is deep integration, not cosmetic

- We ship **5 custom nodes** to RocketRide's ecosystem, including the foundational YouTube live ingest node that doesn't exist upstream.
- We use **the Wave agent (`agent_rocketride`)** as our actual planning loop, with `tool_pipe` to expose sub-pipelines as tools — using the runtime's hierarchical composition primitive, not a workaround.
- We use **`memory_persistent` for the canonical timeline state**, not as a side cache.
- We deploy the **engine in production**, not just at the editor. The C++ engine runs the system at runtime.
- We treat **`.pipe` files as the source of truth** for orchestration. The agent boundaries in our docs map one-to-one to nodes in those files.
- We submit our custom nodes **upstream** to the open-source repo.

This isn't a sticker on the side of the box. RocketRide is the substrate the whole system runs on.

### Concrete code samples

#### `services/gateway/whatif_gateway/rocketride_client.py`

```python
from rocketride import RocketRideClient
import os

ENGINE_URI = os.environ.get("ROCKETRIDE_ENGINE_URI", "ws://localhost:5565")
ENGINE_KEY = os.environ["ROCKETRIDE_API_KEY"]

class RocketRideBridge:
    def __init__(self) -> None:
        self.client = RocketRideClient(uri=ENGINE_URI)

    async def __aenter__(self):
        await self.client.connect(ENGINE_KEY)
        return self

    async def __aexit__(self, *exc):
        await self.client.disconnect()

    async def start_session_perception(self, session_id: str, source_url: str) -> str:
        """Launch the perception pipeline for a session. Returns the engine task token."""
        token = await self.client.use(filepath="pipelines/perception.pipe")
        await self.client.send(
            token,
            payload={"session_id": session_id, "source_url": source_url},
            name="session_start.json",
            mimetype="application/json",
        )
        return token

    async def submit_whatif(self, session_id: str, query_id: str, text: str, anchor_pts_ms: int | None) -> str:
        """Launch the whatif pipeline for a query."""
        token = await self.client.use(filepath="pipelines/whatif.pipe")
        await self.client.send(
            token,
            payload={
                "session_id": session_id,
                "query_id": query_id,
                "text": text,
                "anchor_pts_ms": anchor_pts_ms,
            },
            name="whatif_query.json",
            mimetype="application/json",
        )
        return token
```

#### `agents/_lib/rocketride_events.py`

```python
"""Bridges RocketRide native events into our trace_event table."""
from rocketride import RocketRideClient
from .trace import emit_trace_event

async def consume_engine_events(client: RocketRideClient, token: str):
    async def handle(event):
        body = event["body"]
        if body.get("action") in {"node.started", "node.finished", "node.error"}:
            emit_trace_event(
                agent=f"rocketride:{body.get('node_id')}",
                kind="model_call" if body.get("kind") == "llm" else "tool_call",
                input_ref={"engine_event_id": body["id"]},
                output_ref={"engine_event_payload": body.get("payload")},
                model_id=body.get("model_id"),
                latency_ms=body.get("latency_ms"),
                status="ok" if body["action"] == "node.finished" else body["action"],
                payload={"raw": body},
            )
    await client.subscribe_events(token, ["node.*"], handler=handle)
```
