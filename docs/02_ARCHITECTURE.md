# System Architecture

## Top-level map

```
                            ┌──────────────────────────────────────────┐
                            │              FRONTEND (Web)              │
                            │  Live player · Commentary panel · Timeline scrubber │
                            │  What-if composer · Side-panel alt-reality player    │
                            │  Provenance trace explorer · Share / Director's Cut  │
                            └────────────────┬─────────────────────────┘
                                             │ WebSocket + REST
                                             ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │                       SESSION GATEWAY (FastAPI + WS)                    │
   │   Auth · Session state · Multi-user fan-out · Trace API · Share API     │
   └────────┬────────────────────────────────────────────────────────┬───────┘
            │ event bus (pub/sub)                                     │
            ▼                                                         │
   ┌─────────────────────────────────────────────┐                    │
   │             ROCKETRIDE RUNTIME              │                    │
   │   ┌─────────────┐  ┌─────────────────────┐  │                    │
   │   │ IngestAgent │─►│ FrameCaptionerAgent │──┼──► GMI Cloud       │
   │   └──────┬──────┘  └──────────┬──────────┘  │     (VL, small)    │
   │          │                    │             │                    │
   │          │             ┌──────▼────────┐    │                    │
   │          │             │SummariserAgent│────┼──► Gemini 2.5 Pro  │
   │          │             └──────┬────────┘    │     (video-in)     │
   │          │                    │             │                    │
   │          │             ┌──────▼────────┐    │                    │
   │          │             │MatchStateAgnt │────┼──► GMI Cloud       │
   │          │             └──────┬────────┘    │     (reasoning)    │
   │          │                    │             │                    │
   │          │             ┌──────▼────────┐    │                    │
   │          │             │CommentaryAgnt │────┼──► Gemini Live     │
   │          │             └───────────────┘    │     (streaming)    │
   │          │                                  │                    │
   │          │   user query                     │                    │
   │          │   ┌──────────────┐               │                    │
   │          └──►│RetrievalAgnt │────────┐      │                    │
   │              └──────┬───────┘        │      │                    │
   │                     ▼                ▼      │                    │
   │              ┌──────────────┐ ┌─────────────┐                    │
   │              │DirectorAgnt  │►│ReferenceCut │ ◄── capture buffer │
   │              └──────┬───────┘ └─────────────┘                    │
   │                     ▼                                            │
   │              ┌──────────────┐                                    │
   │              │VideoGenAgnt  │──────────────┼──► Veo (Vertex AI) │
   │              └──────┬───────┘              │                     │
   │                     ▼                      │                     │
   │              ┌──────────────┐              │                     │
   │              │ValidatorAgnt │──────────────┼──► GMI + Gemini    │
   │              └──────┬───────┘              │                     │
   │                     ▼                      │                     │
   │              ┌──────────────┐              │                     │
   │              │CompositorAgnt│              │                     │
   │              └──────┬───────┘              │                     │
   │                     ▼                      │                     │
   │              ┌──────────────┐              │                     │
   │              │  TraceAgent  │ (records every step from every agent) ──┐
   │              └──────────────┘                                       │ │
   └─────────────────────────────────────────────┘                       │ │
            │                                                            │ │
            ▼                                                            ▼ ▼
   ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐
   │ Capture Buffer  │  │ Timeline Index   │  │   Provenance Store           │
   │  (video chunks  │  │  (Postgres +     │  │  (Postgres trace rows +      │
   │   + raw frames) │  │   pgvector for   │  │   blob refs to every input   │
   │  GCS / local FS │  │   embeddings)    │  │   & output artifact)         │
   └─────────────────┘  └──────────────────┘  └──────────────────────────────┘
            ▲
            │ HLS via ffmpeg
   ┌────────┴────────┐
   │  YouTube Live   │
   └─────────────────┘
```

## Layered view

The system is five concentric layers. Each one has a job and a contract with the one inside it.

### L0 — Capture
**Inputs:** A YouTube live URL.
**Outputs:** A continuously growing on-disk archive of timestamped video chunks (default 2-second `.ts` segments) and a parallel stream of decoded frames (default 2 fps reference frames at 720p, plus full-res key frames preserved for Veo reference conditioning).
**Owner:** `IngestAgent`.
**Why this exists:** Everything downstream — every caption, every retrieval, every Veo reference image — comes from this archive. If L0 drops a chunk, the timeline has a hole. So L0 is an isolated, single-job, restart-safe service. It does not talk to LLMs. It only knows ffmpeg.

### L1 — Perception
**Inputs:** Chunks and frames from L0, in order, with timecodes.
**Outputs:** Three parallel streams:
- **Captions stream** — one short structured caption per sampled frame (every ~500 ms), produced by a fast VL model on GMI Cloud.
- **Event summaries** — one structured summary per ~30 s buffer, produced by a stronger video-understanding pass (Gemini 2.5 with video-in, or a high-end VL on GMI). Summaries include detected key events (goals, shots, fouls, subs, set pieces) with frame-precise anchors.
- **Live commentary stream** — a user-facing text feed of the match, opinionated and watchable, produced by Gemini Live consuming the summaries + recent frames.
**Owners:** `FrameCaptionerAgent`, `SummariserAgent`, `MatchStateAgent`, `CommentaryAgent`.

### L2 — Index
**Inputs:** Everything L1 emits.
**Outputs:** A queryable timeline. Two-layer index:
- **Structured index** — Postgres rows: events with start/end timecodes, type tags, involved entities (teams, players, locations), confidence.
- **Semantic index** — pgvector: embeddings of every caption, summary, and event description, with a backref to the underlying frame chunk and event row.
**Owner:** `IndexService` (no agent — it's a write-through service the perception agents call).

### L3 — Counterfactual Generation
**Inputs:** A user "what if" prompt + the current session.
**Outputs:** A validated alternate-reality video clip stored in the artifact store, with a complete trace.
**Owners:** `RetrievalAgent` → `DirectorAgent` → `VideoGenAgent` → `ValidatorAgent` → `CompositorAgent`.

The flow:
1. **Retrieval** — resolve "the moment the user is talking about" using the index (hybrid: explicit timestamp parsing + semantic search + match-state context).
2. **Direction** — build a structured Veo prompt: identify the entities, the counterfactual delta, the camera persona, pick reference frames. This is the prompt-engineering brain of the system.
3. **Generation** — call Veo with the structured prompt + reference frames. Handle async polling. Store the output.
4. **Validation** — a second model watches the generated clip and verifies (a) the counterfactual was respected, (b) visual continuity holds against the reference frames, (c) no obvious physical/temporal artifacts.
5. **Composition** — when more than one what-if exists in the session, the compositor assembles the running director's cut.

### L4 — Experience
**Inputs:** Session events, user actions.
**Outputs:** The frontend experience and the shareable artifact.
**Owners:** `SessionAgent`, `TraceAgent`, the web frontend.

The frontend is a thin client over the session gateway. The session gateway is the WebSocket fan-out and session orchestrator. The trace agent shadows every other agent and writes structured provenance rows so the trace explorer can navigate from "this shareable video" all the way back to "the JPEG of the 24:11 reference frame and the exact Veo prompt that produced this clip."

## Why this shape

Six design decisions justify the shape above:

1. **L0 is one agent doing one thing.** Live ingest is the most failure-sensitive part of the system. Putting it in its own service with no LLM dependencies means it can run alone and restart cleanly without restarting the rest of the system.
2. **The perception pipeline is fan-out, not a chain.** Captioner, summariser, match-state, and commentary all consume the L0 output stream in parallel. None of them blocks another. The captioner can fall behind for 5 seconds without delaying commentary.
3. **The index is the only shared mutable state in L1/L2.** Agents do not pass big payloads around. They write to the index and reference rows by ID. This keeps message sizes tiny and makes the system durable across restarts.
4. **L3 is a strict pipeline, not a graph.** Every what-if request flows the same five-step chain. The flow is the same every time because the artifact must be the same shape every time — that's what makes the trace viewer comprehensible.
5. **Validation is separate from generation.** Veo can produce a clip that looks fine but ignored the counterfactual. A separate model evaluates the output. If it fails, the director rewrites and resubmits.
6. **Trace is a cross-cutting concern.** Every agent emits trace events to a single TraceAgent. The shape of those events is fixed (see `10_PROVENANCE.md`). This is what lets the judges click on a finished video and walk backwards through every step that produced it.

## Component inventory

| # | Component | Type | Tech | Located in |
|---|-----------|------|------|------------|
| 1 | Web frontend | UI | Next.js (App Router) + React | `frontend/` |
| 2 | Session Gateway | Service | FastAPI + websockets | `services/gateway/` |
| 3 | RocketRide Runtime | Agent host | RocketRide | `agents/` |
| 4 | IngestAgent | Agent | ffmpeg, yt-dlp | `agents/ingest/` |
| 5 | FrameCaptionerAgent | Agent | GMI Cloud VL | `agents/captioner/` |
| 6 | SummariserAgent | Agent | Gemini video-in | `agents/summariser/` |
| 7 | MatchStateAgent | Agent | GMI reasoning | `agents/state/` |
| 8 | CommentaryAgent | Agent | Gemini Live | `agents/commentary/` |
| 9 | RetrievalAgent | Agent | pgvector + LLM rerank | `agents/retrieval/` |
| 10 | DirectorAgent | Agent | Gemini 2.5 Pro | `agents/director/` |
| 11 | VideoGenAgent | Agent | Veo (Vertex AI) | `agents/videogen/` |
| 12 | ValidatorAgent | Agent | Gemini + GMI VL | `agents/validator/` |
| 13 | CompositorAgent | Agent | ffmpeg | `agents/compositor/` |
| 14 | SessionAgent | Agent | RocketRide native | `agents/session/` |
| 15 | TraceAgent | Agent | RocketRide native | `agents/trace/` |
| 16 | IndexService | Service | Postgres + pgvector | `services/index/` |
| 17 | CaptureBuffer | Storage | Local FS + GCS | `infra/storage/` |
| 18 | ProvenanceStore | Storage | Postgres + GCS blobs | `infra/storage/` |
| 19 | ArtifactStore | Storage | GCS + signed URLs | `infra/storage/` |

## Synchronous vs asynchronous boundaries

- **Synchronous (request/response):** retrieval-to-direction-to-validation. The user request enters and exits the same WebSocket round-trip (with progress events).
- **Asynchronous (always-on stream):** ingest → perception → index. Runs whether anyone is asking what-ifs or not. Backpressure: if perception falls behind, captions are dropped before summaries are dropped before the index is allowed to skew.
- **Background (queue-driven):** video generation. Veo is the slowest hop. The session gateway streams progress (queued → reference cut → veo polling → validating → ready) to the user.

## Latency budget for a what-if

Total time from user submit to playable clip:

| Stage | Target | Hard limit |
|---|---|---|
| Retrieval | 200 ms | 1 s |
| Reference cut from buffer | 400 ms | 2 s |
| Director prompt composition | 1.5 s | 4 s |
| Veo generation | 30–60 s | 120 s |
| Validation | 3 s | 8 s |
| Total | ~40 s typical | 135 s worst |

The live match keeps playing. The user sees a structured progress UI for the 40s and can keep watching the broadcast and even queue further what-ifs while the first one cooks.

## Failure modes and recovery

- **YouTube stream drops.** Ingest reconnects with exponential backoff; the index marks a gap.
- **Captioner falls behind.** Frames queue. Drop oldest unsampled frames first; keep one frame per second floor.
- **Summariser falls behind.** Summaries can be late by up to 2 buffers without UX harm. Beyond that, mark the gap and continue.
- **Veo fails or times out.** Validator catches, director regenerates with a simpler prompt once. After two failures, return a structured error to the user with the partial trace so they can adjust the question.
- **Validator rejects the output.** Director gets one regeneration attempt with the validator's specific complaints injected as constraints. If it still fails, surface to user.
- **Session disconnect.** Agents continue. State persists. User reconnect resumes the session with the timeline rebuilt from the index.

Every failure is a trace event. Nothing fails silently.
