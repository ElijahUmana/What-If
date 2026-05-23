# Build Team Task Decomposition

Tasks below are sized for parallel execution by an agent team of 4–5 workers. Each task is self-contained: the working notes, success criteria, and dependencies are inline. Each task can be picked up by any team member; the lead assigns and tracks via the `TaskCreate` / `TaskUpdate` tooling.

Critical-path dependencies are tagged.

## Wave 1 — Substrate (parallel, no dependencies)

### T1. Repo scaffold
- Initialise pnpm workspaces, uv project, ESLint/Prettier/ruff/mypy configs.
- Create the directory tree from `14_REPO_LAYOUT.md`.
- Add `.env.example` with every required variable from `13_INFRA.md`.
- Wire up Make targets: `make dev`, `make test`, `make lint`, `make build`.
- **Done when:** `make dev` boots gateway + frontend + Postgres + NATS without errors.

### T2. Postgres + pgvector schema + migrations
- Implement migrations 0001–0003 covering every table in `03_DATA_MODEL.md`.
- Generate Pydantic models in `schemas/domain/` from the migration definitions.
- Generate TypeScript types in `schemas/ts/`.
- Add a minimal seed script for local dev.
- **Done when:** `alembic upgrade head` produces every table; round-trip Pydantic ↔ TS types compile.

### T3. Session gateway skeleton
- FastAPI app with health, version, and `/api/sessions` POST endpoint.
- WebSocket route at `/ws/sessions/:id` with the event-envelope protocol from `11_FRONTEND.md`.
- Auth shim (accept a signed cookie; no full auth yet).
- **Done when:** can POST a session, connect a WS, receive `session.started` event.

### T4. Frontend shell
- Next.js 15 app boot. Landing page with URL input. Session view skeleton with all components in `11_FRONTEND.md` stubbed in.
- WebSocket client with reconnect.
- Zustand store with shape `SessionState`.
- **Done when:** can paste a URL, hit submit, navigate to `/session/[id]` with WS connected.

### T5. RocketRide runtime + agent skeletons
- Install RocketRide locally per its docs (`07_TECH_ROCKETRIDE.md`).
- Create empty agent yamls + Python stubs for every agent in `05_AGENTS.md`.
- Each agent at this stage: receives its trigger event, logs it, emits a trace span, exits.
- **Done when:** `rocketride dev` lights up all 13 agents; firing a synthetic event into the bus walks through each agent.

## Wave 2 — Perception layer (depends on Wave 1)

### T6. IngestAgent
- Implement `youtube_resolver.py` using yt-dlp.
- Implement `ffmpeg_pipeline.py` with the dual-output ffmpeg command from `04_PIPELINE.md` A1.
- Watchdog for new files → GCS upload → Postgres insert → bus emit.
- Restart safety.
- Unit tests using a sample HLS playlist.
- **Done when:** pasting a real live YouTube URL produces chunks and frames in GCS with rows in Postgres at the expected rate.

### T7. FrameCaptionerAgent
- GMI Cloud client in `agents/_lib/gmi.py`.
- Captioner prompt + concurrency-bounded worker.
- Embedding call.
- **Done when:** captions land in Postgres at 2/s with reasonable text.

### T8. SummariserAgent
- Tumbling 30 s window subscription.
- Gemini multimodal call with concatenated chunk MP4s.
- Structured output + event extraction.
- Auto-expand logic.
- **Done when:** summaries land at 1 per 30 s; events are detected on a known test clip.

### T9. MatchStateAgent
- Transition engine + LLM call for ambiguous deltas.
- Redis cache write.
- **Done when:** state evolves correctly through a known test sequence (goal → score++, sub → on-pitch update).

### T10. CommentaryAgent
- Gemini Live WebSocket session.
- Inputs from summaries + events.
- Tokens streamed to gateway → frontend.
- **Done when:** the right-column commentary panel shows live text during a real match.

### T11. SetupAgent
- One-shot match-meta identification.
- **Done when:** session view header shows correct teams + competition for any major-league live URL.

## Wave 3 — Index + retrieval (depends on Wave 2 producing rows)

### T12. IndexService
- Write-through API used by Wave 2 agents.
- pgvector queries: top-k semantic search with hybrid filters.
- **Done when:** can semantically search "shots on goal in the last 5 minutes" and get the right events back.

### T13. RetrievalAgent
- Parse + embed + search + rerank pipeline.
- Clarification fork when ambiguous.
- **Done when:** for a battery of fixture queries against a recorded session, picks the right anchor 90%+ of the time.

## Wave 4 — Counterfactual generation (depends on Wave 3)

### T14. DirectorAgent
- Reference-frame selection logic.
- Structured Veo prompt composition via Gemini.
- **Done when:** for fixture inputs, produces well-formed Veo bodies that pass a JSON-schema validator.

### T15. VideoGenAgent
- Veo client wrapping the Vertex AI LRO.
- Async polling + result download.
- **Done when:** end-to-end submit → poll → MP4 in GCS works for canned prompts.

### T16. ValidatorAgent
- Two parallel checks (Gemini fidelity + GMI VL continuity).
- Verdict merge.
- **Done when:** validator distinguishes "counterfactual honoured" from "ignored" on a hand-labelled set of 20 clips.

### T17. CompositorAgent
- Per-clip branch-card overlay (ffmpeg drawtext + image overlay).
- Reel concatenation.
- HLS variant generation.
- **Done when:** producing a director's cut from 3 clips yields one playable MP4 + HLS.

## Wave 5 — Frontend completion (parallel with Wave 4)

### T18. Live player + timeline scrubber
- HLS playback wired to gateway-resolved manifest.
- Scrubber rendering with event chips.
- Right-click menu.
- **Done when:** timeline updates in real time as events land.

### T19. What-if composer + clip tray + alt-reality overlay
- Composer with suggestion chips.
- Clip tray with in-progress and ready cards.
- Alt-reality overlay with dual-audio ducking.
- Branch action.
- **Done when:** complete what-if round trip is visible from submit to play.

### T20. Trace explorer UI
- Two-pane layout.
- Lazy tree loading.
- Renderer per `kind`.
- Replay button.
- **Done when:** can walk from any clip back to every contributing artifact.

### T21. Sharing pages
- `/c/[short_code]`, `/cut/[short_code]`, `/embed/c/[short_code]`.
- SSR with OG tags.
- Imagen 4 OG-image generation.
- **Done when:** sharing a link unfurls correctly in Slack and Twitter and plays in-browser.

## Wave 6 — Operability (parallel with everything)

### T22. TraceAgent + replay tooling
- Trace persistence with local WAL fallback.
- Read API.
- Export ZIP builder with bundled `viewer.html`.
- **Done when:** trace API serves the full tree for any session; ZIP opens offline.

### T23. CI + observability
- GitHub Actions workflow: lint, typecheck, unit, integration on PR.
- Structured logging shipped to Cloud Logging.
- Cloud Monitoring dashboards.
- **Done when:** PRs gated; ops dashboard shows per-agent QPS/p99.

### T24. Terraform + deploy
- Provisioning of GCP project + Cloud Run + Neon + Cloudflare DNS.
- Image build + push + release scripts.
- **Done when:** `make release` pushes new images and routes the next deploy.

## Definition of done (entire system)

A live Premier League / Champions League match URL pasted into the production app must produce:

1. A timeline that fills in within 30 s of paste with the correct match meta.
2. A live commentary feed that begins speaking within 60 s of paste.
3. A what-if request anchored at any event in the timeline that produces a validated, playable, visually-continuous alt-reality clip within the latency budget in `02_ARCHITECTURE.md`.
4. A complete trace explorable from the clip back to the source frame.
5. A shareable director's-cut URL at session end with all clips composed.

No partial paths. No "this feature isn't wired up yet." Either it is delivered to the standard above, or it is not done.
