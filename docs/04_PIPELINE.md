# The End-to-End Pipeline

Two pipelines run in this system. The **perception pipeline** runs continuously for the lifetime of the session — driven by the broadcast itself, not by user actions. The **counterfactual pipeline** runs in response to each user "what if" — many of them per session, potentially concurrent.

## Pipeline A — Perception (continuous, broadcast-driven)

### A0. Stream resolve
- User submits a YouTube URL to the session gateway.
- `IngestAgent` calls `yt-dlp -g --live-from-start` to resolve the live HLS manifest URL.
- A `match_meta` extraction agent fires once: pulls the YouTube title/description, asks an LLM to extract `{home_team, away_team, competition, kickoff_at}`, writes to `session.match_meta`. This is needed so the perception layer can disambiguate kit colours and players from the very first frame.

### A1. Continuous capture
- `IngestAgent` runs ffmpeg as a long-lived subprocess:
  ```
  ffmpeg -i <hls_manifest_url> \
         -c copy -map 0 \
         -f hls -hls_time 2 -hls_list_size 0 -hls_segment_type mpegts \
         -hls_segment_filename "chunks/%08d.ts" "chunks/index.m3u8" \
         -vf "fps=2,scale=1280:720" -q:v 4 "frames/%010d.jpg"
  ```
- Each new `.ts` chunk and each new reference frame triggers a watcher → writes a `chunk` row and a `frame` row → publishes `chunk.created` and `frame.created` events on the agent bus.
- Capture is GPU-accelerated where available (`-hwaccel cuvid -c:v h264_cuvid` for decode).
- The agent is restart-safe: on crash, it re-reads the manifest, fast-forwards to the latest sequence, and resumes.

### A2. Per-frame captioning (fast)
- `FrameCaptionerAgent` subscribes to `frame.created`.
- For each frame: download from object store → POST to GMI Cloud chat completions with the frame as a `image_url` content block → prompt asks for one-line description plus structured entity tags (`{players_visible, ball_position, action, scene}`).
- Writes `caption` row + embedding row.
- Target throughput: 2 captions/sec/session. Two concurrent in-flight requests per session via a tiny worker pool.
- Model: smallest competent VL on GMI Cloud (target ~600 ms p50).

### A3. Buffered summarisation (deep)
- `SummariserAgent` runs on a 30-second tumbling window. Every 30 s of source time:
  - Pulls the last ~60 frames (2 fps × 30 s) and the last ~60 captions.
  - For non-eventful windows: ask the summariser model to produce a paragraph + structured `{phase, possession, dangerous_situation, key_action, players}`.
  - For eventful windows (high motion / shot-detected via VL prior pass): ask the deep video-understanding model with the actual video chunks as input — extracts events with frame-precise anchors.
- Writes `summary` row + 0..N `event` rows + embeddings.
- Dynamic expansion: if a detected event has `confidence < 0.7`, the agent automatically requests a wider window (60 s, then 90 s) before committing the event.

### A4. Match state update
- `MatchStateAgent` subscribes to `summary.created` and `event.created`.
- Maintains a versioned `match_state` row keyed by `as_of_pts_ms`.
- Each new summary updates score (only when goal event fires), possession (rolling), period clock (computed from kickoff anchor), on-pitch players (updated by sub events).
- The current `match_state` is cached in Redis for sub-ms reads.

### A5. Live commentary
- `CommentaryAgent` runs a Gemini Live session for the whole match.
- Inputs streamed in: every new summary + the current match state + the latest 3 reference frames.
- Outputs streamed out: an opinionated, watchable text feed pushed to the session gateway → WebSocket → frontend.
- This is the only agent that runs as a persistent streaming session rather than request/response. It keeps Gemini's context warm so it can be conversational.

### A6. Index write-through
- Every caption, summary, event lands in pgvector with a 1024-d embedding.
- Embeddings are produced by an embedding model hosted on GMI Cloud.

## Pipeline B — Counterfactual (per user query)

### B0. Query intake
- User submits text into the what-if composer.
- Session gateway creates a `query` row, sets `status=received`, returns the query ID to the frontend so the UI can stream progress.

### B1. Resolve
- `RetrievalAgent` parses the user's text:
  1. **Explicit timestamp parse** — if the user wrote "at 24:11" or right-clicked a timeline marker.
  2. **Semantic search** — embed the user text → query pgvector → top-k events + summaries.
  3. **Match-state grounding** — pull the current `match_state` so the agent can resolve "the striker" or "the keeper" to a name.
  4. **LLM rerank** — Gemini reasoning call over the top-k results + the user text + the current state, returns: `{anchor_event_id, anchor_pts_ms, window_start_ms, window_end_ms, change_type, entities_referenced, intent}`.
- Writes parsed fields to `query`. Status → `resolved`.

### B2. Direct
- `DirectorAgent` takes the resolved query and composes the generation plan:
  1. **Pull reference frames.** Fetch 4–8 frames spanning the window: one before the counterfactual moment for setting/character, one at the moment for camera angle, two after for continuation context. Choose key frames (full resolution).
  2. **Build the structured prompt.** A schema-driven prompt with sections:
     - SCENE: stadium, weather, broadcast camera persona.
     - CONTINUITY: kit colours for both teams, named players visible, ball position.
     - REAL EVENT: what actually happened (from the anchor event).
     - COUNTERFACTUAL: the specific change the user requested, written in directable language.
     - CONTINUATION: what should happen next (the agent invents a plausible 8-second continuation consistent with the change).
     - AUDIO: crowd reaction matching the new outcome; optional broadcaster line.
     - NEGATIVE: things the model must avoid (jersey colour swaps, player teleporting, scoreboard hallucinations).
  3. **Write the `prompt` row.** Status → `directing` done.

### B3. Generate
- `VideoGenAgent` submits the prompt + reference frames to Veo (Vertex AI).
- Veo is an async operation: get a long-running operation ID, poll until done, fetch the result MP4.
- Polling cadence: 2 s for the first 30 s, then 5 s.
- The generated MP4 is downloaded to the artifact bucket. `generation` row written. Status → `validating`.

### B4. Validate
- `ValidatorAgent` runs three checks in parallel:
  1. **Counterfactual fidelity** — Gemini watches the generated clip and answers "did the requested change occur?" with reasoning.
  2. **Visual continuity** — a VL model on GMI Cloud compares 2 sampled frames of the generated clip against the reference frames: kit colours match, stadium dressing matches, no extra ball.
  3. **Physical sanity** — checks for obvious artifacts (player limbs, ball passing through bodies, instant teleportation).
- Verdict: `ok`, `regenerate`, or `reject`.
- If `regenerate`, director rewrites the prompt incorporating validator's specific complaints and resubmits B3 once. Beyond that, reject.

### B5. Compose + present
- `CompositorAgent` produces the user-facing playable artifact:
  - If this is the first what-if, the clip itself is the artifact.
  - The composer also keeps a running "session reel" that prepends a 1-second branch card before each what-if (showing the real match clock and the user's prompt).
- `clip` row written. Status → `ready`.
- Session gateway pushes a `clip.ready` event to the user's WebSocket → frontend pops the alt-reality side panel.

## Concurrency and ordering

- Pipeline A is always running, never paused by Pipeline B.
- Multiple Pipeline B requests can be in flight from the same session simultaneously. They are independent — each gets its own resolve/direct/generate/validate chain.
- A what-if can branch from an existing clip (`query.parent_clip_id` set). When this happens, the retrieval agent uses the parent clip's final frame and its continuation context as the new anchor, instead of the live broadcast.

## What we never do

- We never seek the live player backwards. The live broadcast keeps playing on the main canvas. All retrospection happens server-side from the capture buffer.
- We never modify the original broadcast pixels. The output is always a separate, labelled clip.
- We never produce a Veo prompt that doesn't reference the actual frames. Reference-conditioned generation only; never blind text-to-video.
