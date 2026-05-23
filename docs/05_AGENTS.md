# Agent Topology

Every agent has: a **name**, a **trigger** (what wakes it up), a **contract** (inputs and outputs), a **model assignment**, a **failure policy**, and a **trace footprint** (what it must emit to the provenance store). Agents do not call each other directly — they read from the event bus and write to the index/artifact store. Indirection is the point: it is what lets a single agent be restarted, replaced, or rerun without cascading.

The runtime is **RocketRide**. Each agent below maps to a RocketRide agent definition under `agents/`. The runtime takes care of model routing, observability, deployment, and message passing; we author business logic only.

## Cross-cutting conventions

- **One side-effect class per agent.** Either it writes to the index, or it writes an artifact, or it emits an event. Never two.
- **All work is idempotent.** Re-delivery of an event must not double-write. Idempotency key = the source event ID.
- **Trace emission is mandatory.** Every agent wraps its main handler in a trace span. Every external model call is its own child span.
- **No agent reaches for global state.** The bus delivers what the agent needs.

---

## 1. IngestAgent

**Role:** Own the live stream. Convert YouTube live → on-disk chunks + decoded reference frames.
**Trigger:** `session.start` event.
**Inputs:** `{session_id, source_url, source_kind}`.
**Outputs:** Long-lived. Emits `chunk.created` and `frame.created` events as files land.
**Models:** None. Pure systems work.
**Implementation:**
- Subprocess: ffmpeg with HLS segmenter + a separate fps=2 frame extractor (the two outputs run in parallel from one input via `-map` and a tee filter).
- File watcher (watchdog) on the chunk and frame dirs → on close-write, upload to GCS, insert row, publish event.
- Restart policy: process supervisor; on fail, re-resolve manifest, fast-forward.
**Failure policy:**
- Stream drop → 3 reconnect attempts with backoff (2s, 5s, 15s) → if still failing, mark session ingest as `errored` and notify gateway.
- Disk full → emit alert, halt extraction, keep manifest pointer for restart.
**Trace:** one span per chunk, one per frame, one parent `ingest.session` span open for the session lifetime.

---

## 2. SetupAgent (match metadata)

**Role:** One-shot at session start. Identify teams, competition, kit colours.
**Trigger:** `session.start`, runs once.
**Inputs:** `{session_id, source_url}`.
**Outputs:** Updates `session.match_meta`.
**Models:** Gemini 2.5 Pro (web tool + the first few seconds of frames).
**Implementation:**
- Pulls YouTube title/description via oEmbed.
- Pulls the first 10 frames once they exist.
- One Gemini call with system prompt: "Identify the football match. Return JSON: {home_team, away_team, competition, kickoff_at_utc, broadcaster, home_kit_color, away_kit_color, gk_home_kit, gk_away_kit, stadium}."
- Falls back to a structured-mode call if free-form fails.
**Failure policy:** Two retries; on continued failure, mark `match_meta.unknown=true` and proceed — downstream agents can still operate without identified teams, with reduced player-resolution accuracy.
**Trace:** one span containing the prompt and the structured output.

---

## 3. FrameCaptionerAgent

**Role:** Per-frame VL captioning at high QPS.
**Trigger:** `frame.created`.
**Inputs:** `{frame_id, session_id, storage_uri, pts_ms}`.
**Outputs:** `caption` row + embedding row.
**Models:** GMI Cloud — smallest competent VL (target Qwen2.5-VL-7B or Llama-3.2-11B-Vision class, whichever has lower p50 on the GMI fleet today).
**Implementation:**
- Signed-URL the frame into the model request as `image_url`.
- System prompt locks the model into football vocabulary, returns JSON `{caption, ball_visible, players_visible_count, scene_type, confidence}`.
- Embedding produced by a separate small embedding-model call on GMI.
- Concurrency: max 4 in-flight per session; drop oldest unsampled if backlog > 8.
**Failure policy:**
- 5xx from GMI → retry once with 200 ms backoff; on second fail, log error caption (`text="<unavailable>"`) and continue. We never block the pipeline on captioning.
**Trace:** one span per frame; child span for model call.

---

## 4. SummariserAgent

**Role:** Aggregate ~30 seconds of frames into a structured summary + event detection.
**Trigger:** Tumbling window timer per session (every 30 s of source time).
**Inputs:** the frames and captions within `[window_start_ms, window_end_ms]`.
**Outputs:** `summary` row + 0..N `event` rows + embeddings.
**Models:**
- Default: Gemini 2.5 with video chunks as input (handles up to several minutes of video per request).
- Fallback: high-end VL on GMI Cloud (e.g. Qwen2.5-VL-72B) over the sampled frames if Gemini is rate-limited.
**Implementation:**
- Builds a single multi-modal prompt with the chunk MP4s (concatenated via ffmpeg into a single short clip for the window).
- Structured-mode output: schema enforces `{narrative, structured: {phase, possession, dangerous_situation, key_action, players}, events: [{type, start_pts_ms, end_pts_ms, actors, description, confidence}]}`.
- Auto-expand: if `events[].confidence < 0.7`, the agent re-queries with an expanded window (window_start − 30 s, window_end + 30 s). Up to two expansions.
**Failure policy:** Skip window on hard fail, mark gap in index. Pipeline must not stall.
**Trace:** one span per window; child spans for each expansion, each event emission.

---

## 5. MatchStateAgent

**Role:** Maintain the running game-state model (score, period, on-pitch, momentum).
**Trigger:** `event.created` and `summary.created`.
**Inputs:** the new event/summary + the most recent `match_state` row.
**Outputs:** a new `match_state` row + Redis hot-cache write.
**Models:** GMI Cloud — fast reasoning model (e.g. Llama-3.3-70B class) in structured-output mode.
**Implementation:**
- Prompt: "Given the prior state and this new event, return the next state." JSON schema-locked.
- The agent does NOT free-form. It applies deterministic transitions where possible (goal events → score +1) and only LLM-calls when the structured update is genuinely ambiguous (e.g. inferring a substitution from a tracking shot of the touchline).
**Failure policy:** Reject malformed transitions; keep prior state and log.
**Trace:** one span per transition; the diff between prior and next state is recorded as the trace payload.

---

## 6. CommentaryAgent

**Role:** Produce the live, watchable AI commentary feed.
**Trigger:** `session.start`, runs as a persistent Gemini Live session.
**Inputs (streamed):** every new summary, every event, the current match state, the most recent reference frame.
**Outputs (streamed):** text tokens delivered to the session gateway → frontend.
**Models:** Gemini Live (Gemini 2.5 Flash live variant, audio or text mode).
**Implementation:**
- Opens a WebSocket to the Gemini Live endpoint at session start.
- Streams in compact updates: `{"event": event_json}` and `{"summary": summary_json}`.
- Streams out text tokens; gateway forwards to frontend.
- Persona: "concise broadcast commentator, watch the action with the user, react to events as they happen, never speculate beyond what the perception layer has told you."
**Failure policy:** Drop and restart the Live session on disconnect; the perception pipeline is unaffected.
**Trace:** one long span per Live session; inputs and outputs are appended as sub-events.

---

## 7. RetrievalAgent

**Role:** Resolve a user "what if" prompt to a precise anchor and window.
**Trigger:** `query.received`.
**Inputs:** `{query_id, session_id, text, parent_clip_id?}`.
**Outputs:** Updates `query.parsed`, `query.resolved_*`. Emits `query.resolved`.
**Models:**
- Embedding model on GMI Cloud for semantic search.
- Gemini 2.5 Pro for the rerank/parse step.
**Implementation:**
1. Parse the user text for explicit timecodes ("at 24:11").
2. Embed and search across captions, summaries, events. Top 20 candidates.
3. Build a rerank prompt with: current match state, the top-20 candidates, and the user text. Ask the LLM to choose the right anchor and define the window. JSON output.
4. If the prompt has `parent_clip_id`, anchor on the parent clip's final frame instead.
**Failure policy:** If retrieval is ambiguous, return a structured clarification ("you might mean A or B") and let the user choose. Never silently guess.
**Trace:** one span; child spans for the search, the rerank, the clarification fork.

---

## 8. DirectorAgent

**Role:** Compose the structured Veo prompt and pick reference frames.
**Trigger:** `query.resolved`.
**Inputs:** the resolved query + the window's frames, captions, summary, event, match state.
**Outputs:** a `prompt` row of kind `veo_ref_conditioned`. Emits `prompt.ready`.
**Models:** Gemini 2.5 Pro in structured-output mode.
**Implementation:**
- Loads the window's frames (4–8 keyframes), captions, summary, event, match state.
- Calls Gemini with a system prompt that produces the structured Veo body (see `08_TECH_GEMINI_VEO.md`).
- Picks reference frames: the agent itself outputs which frame indices to include — it knows the camera angles and the change moment best.
**Failure policy:** Validator-driven regeneration loop (see `04_PIPELINE.md` B4).
**Trace:** one span containing the system prompt, the input bundle, and the resulting structured prompt.

---

## 9. VideoGenAgent

**Role:** Wrap Veo. Submit, poll, persist.
**Trigger:** `prompt.ready` for prompts of kind `veo_*`.
**Inputs:** the prompt row.
**Outputs:** a `generation` row, the MP4 in object storage.
**Models:** Veo (Vertex AI long-running operation API).
**Implementation:**
- Submit the generation. Get LRO name.
- Poll until done.
- Stream-download the MP4 to GCS.
- Hand off to validator.
**Failure policy:** One retry on transient errors. Permanent errors marked on the `generation` row with the Vertex error code.
**Trace:** one span per submission; sub-events for each poll tick.

---

## 10. ValidatorAgent

**Role:** Decide whether the generated clip honoured the counterfactual and stayed visually continuous.
**Trigger:** `generation.complete`.
**Inputs:** `{generation_id, prompt_id, clip_uri, reference_frame_uris[]}`.
**Outputs:** Updates `generation.validator_verdict` and `validator_reasons`. Emits `generation.validated` or `generation.regenerate`.
**Models:**
- Gemini 2.5 Pro with the generated MP4 + reference frames in one call (fidelity check).
- Qwen2.5-VL on GMI Cloud for fast frame-by-frame continuity check.
**Implementation:**
- Two parallel calls; merge results.
- Verdict logic: both must pass for `ok`; one fail = `regenerate` with merged reasons; both fail = `reject`.
**Failure policy:** If validator itself errors, treat as `ok` with a flag (never block a user clip on validator infrastructure failure, but log it loudly).
**Trace:** one parent span; two child model spans; final verdict recorded.

---

## 11. CompositorAgent

**Role:** Produce the user-facing playable artifact and the running director's-cut reel.
**Trigger:** `generation.validated` and `artifact.export_requested`.
**Inputs:** validated clips for the session.
**Outputs:** `clip` row, `artifact` row, MP4s in object storage.
**Models:** None (pure ffmpeg).
**Implementation:**
- Per-clip output: 1 s branch card (PNG generated from a Jinja template + ffmpeg) prepended to the Veo clip. Same encoder settings as the original. Audio normalised.
- Session reel: concat of all validated clips in order, with title card and outro.
**Failure policy:** ffmpeg failures are reported per-clip; the reel falls back to the raw clip without branch card.
**Trace:** one span per compose; the ffmpeg command line is captured.

---

## 12. SessionAgent

**Role:** Own the user-facing session: state machine, multi-user fan-out, query queue.
**Trigger:** WebSocket connect + every user action.
**Inputs:** user events from the gateway.
**Outputs:** authoritative session state events; routes user queries into the bus.
**Models:** None.
**Implementation:**
- State machine: `init → ingesting → live → closing → closed`.
- Multi-user: a session can have multiple connected clients; the agent broadcasts every state change to all subscribers.
- Query queue: per-session FIFO; the agent rate-limits queries (default 3 in-flight per session) and surfaces queue position.
**Failure policy:** Never drop a query silently. On internal failure, queries return a structured error.
**Trace:** one span per user action.

---

## 13. TraceAgent

**Role:** Aggregate the trace stream and serve the provenance API.
**Trigger:** Every `trace.emit` event on the bus.
**Inputs:** trace events from every agent.
**Outputs:** `trace_event` rows; the read API the frontend uses for the trace explorer.
**Models:** None.
**Implementation:**
- Batched inserts (100/s flush).
- The read API supports tree-walk queries: "give me all descendants of trace tr_X."
- Exports: on request, packages the full trace of a session (or a single artifact) as a downloadable ZIP containing every input/output artifact referenced by every span.
**Failure policy:** Trace writes are best-effort; never block a producer on trace persistence. Local agents buffer to disk if Postgres is unreachable.

---

## Agent communication

Inside RocketRide, agents communicate via the runtime's pub/sub. Each event has:

```json
{
  "event_id": "ev_…",          // ULID
  "kind": "frame.created",
  "session_id": "ss_…",
  "produced_by": "agent:ingest",
  "produced_at": "2026-05-23T13:24:11.045Z",
  "payload": { "frame_id": "fr_…", "pts_ms": 1452045 },
  "parent_trace_id": "tr_…"
}
```

Agents subscribe by kind. Delivery is at-least-once with idempotency keys. Order is per-session (RocketRide guarantees per-key ordering on the pub/sub backend).

## Why RocketRide here specifically

This system is a fleet of long-running, narrow, observable agents. The alternative is to write 13 services by hand, glue them with a message queue, hand-roll the trace plumbing, build a config system for which model goes to which agent, and ship a separate deploy for each. RocketRide gives us all of that as the substrate — agent declarations, model routing, deployment, observability, and the editor integration our team uses to author and debug agents. Using it as that substrate is the deep integration; using it as a thin wrapper around one model call would be cosmetic and the kind of thing the hackathon explicitly disqualifies.
