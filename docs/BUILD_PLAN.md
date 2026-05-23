# What If — Hackathon Build Plan (verified, two-person execution)

*Companion to `What_If_Master_Plan.md`. That file is the full architecture; this file is what we actually do today and who does what.*

---

## 1. Live Verification — what I just confirmed end-to-end

Every claim below was just tested against the real source URL (`https://www.youtube.com/watch?v=ZS7-0zjC_rg`) and the real provider endpoints from this machine.

| Surface | Status | Evidence |
|---|---|---|
| YouTube URL — non-DRM, live, ingestable | **YES** | yt-dlp resolved manifest, format `300 1280x720 60fps avc1+aac` available. Title: `🔴LIVE : Valencia vs Barcelona | La Liga 2026 | Full Match Streaming | PES 21 Simulation Video`. |
| Manifest URL hits googlevideo CDN | **YES** | `HTTP 200` in 2.07 s, 2.3 MB initial playlist. |
| ffmpeg captures live HLS to chunks + frames | **YES** | 20-second smoke test produced 4 × 2-second `.ts` chunks (~1 MB each) and 40 × 720p JPEG frames (~95 KB each). Capture speed `1.6× realtime`, sustainable. |
| Frames are visually broadcast-grade | **YES** | Saw frame: scoreboard reads `VAL 0-0 BAR  54:15`, players in formation, kit colors clear (Valencia white / Barcelona blue+maroon), camera angle is standard broadcast wide. Perfect Veo reference material. |
| yt-dlp current (`2026.03.17`) + JS runtime | **YES, with one tweak** | macOS already had Node; YouTube extraction now requires either Deno *or* `--remote-components ejs:github` + Node. Deno just got installed via Homebrew on this machine; Node fallback also confirmed working. |
| ffmpeg 8.x with HW accel | **YES on Mac** (VideoToolbox), **needs NVIDIA build on RunPod** (`h264_cuvid`). Software fallback works fine at 720p. |
| `https://api.gmi-serving.com/v1/models` | **LIVE** (HTTP 401, expected — needs key). |
| `https://docs.gmicloud.ai` | **LIVE** (HTTP 200). |
| `https://console.gmicloud.ai` | **LIVE** (HTTP 200). |
| `https://generativelanguage.googleapis.com/v1beta/models` | **LIVE** (HTTP 403, expected — needs key). |
| `https://ai.google.dev`, `https://aistudio.google.com/apikey` | **LIVE**. |
| RocketRide PyPI `rocketride==1.1.0` | **LIVE**, requires Python ≥ 3.10. |
| RocketRide GitHub repo + docs | **LIVE** (HTTP 200). |
| GHCR engine image `rocketride-org/rocketride-engine:latest` | **LIVE** (HTTP 401 to manifest is normal — image registry requires auth headers, image itself is public). |

**One important reality check on the source.** The link is a PES 21 video-game simulation, not a real La Liga broadcast. That is **good for our pipeline**: it has scoreboard overlays, broadcast camera angles, kit-coloured players, crowd, and ad boards — everything the perception layer needs — with zero DRM risk. Real top-flight live streams on official YouTube channels are DRM-protected and yt-dlp cannot capture them, so building against this PES stream is the safer choice. The judges will not care; the system is content-agnostic and demonstrates the same capability.

---

## 2. Risk Register — every concern from earlier, now with concrete mitigations

| # | Concern | Status | Mitigation (in code) |
|---|---|---|---|
| R1 | Source live + non-DRM | **RESOLVED** | Use the verified URL. Keep a backlog of 2–3 other PES-style live streams as backups. |
| R2 | yt-dlp JS runtime requirement | **RESOLVED** | Deno installed. Backup: `--remote-components ejs:github --js-runtimes node`. Both confirmed working from this machine. |
| R3 | YouTube "Sign in to confirm you're not a bot" | **RESOLVED** | Always pass `--cookies-from-browser chrome` (or firefox/safari). Tested working. |
| R4 | GMI Cloud Tier 1 = 100K TPM | **OPEN — action now** | Charge $50 to GMI account at registration desk to unlock Tier 2 (2M TPM) — applies within 24 h. Simultaneously email `support@gmicloud.ai` requesting hackathon tier bump. Until then, route the *fast* captioner to Gemini Flash Lite (not GMI). |
| R5 | Gemini free tier 15 RPM on 3.5 Flash | **MITIGATED IN PLAN** | Enable billing on the Gemini API key day-of. The summariser only fires every 30 s (= 2 RPM) so it stays comfortably in free tier; the captioner uses 3.1 Flash Lite (cheaper) with billing on. |
| R6 | Veo 3.1 is Preview, not GA | **ACCEPTED** | Default to `veo-3.1-fast-generate-preview` (30–45 s). Fall back to `-lite` if the Fast queue spikes. Generate concurrently when multiple what-ifs queue. |
| R7 | Veo retains output only 2 days | **MITIGATED IN PLAN** | `VideoGenAgent` downloads the MP4 to our GCS bucket immediately on LRO completion. Trace records the local URI; we never depend on Veo's server-side retention. |
| R8 | Gemini Live 2-min cap on audio+video | **MITIGATED IN PLAN** | We do audio-only-output + text-event-input (15-min cap), with 110-second session rotation. The agent rotates seamlessly. |
| R9 | `google-genai` SDK typing bug on reference images (#1988) | **MITIGATED IN PLAN** | `agents/_lib/veo.py` has `safe_reference_image()` that bypasses the typing path. Pin SDK to latest. |
| R10 | GMI has no serverless embeddings | **CHANGED — drop the dedicated endpoint** | Use Google `text-embedding-004` via Gemini API (free tier covers our volume). The GMI dedicated-endpoint path stays in the master plan as a future option; not on the critical path today. |
| R11 | Veo SDK + Live SDK on same `google-genai` install | **OK** | Both ship in the same SDK. Single `pip install google-genai`. |
| R12 | RocketRide engine is stateful, long-running | **OK** | Engine runs in a single container on RunPod. Gateway and frontend can be serverless / Cloud Run; only the engine + ingest is stateful. |
| R13 | RunPod vs Modal | **DECIDED** | RunPod RTX 4090 ($0.39/hr) hosts ingest + RocketRide engine. Modal functions handle Veo polling and validator bursts. |
| R14 | Postgres + pgvector + GCS provisioning | **OK** | Neon (Postgres + pgvector, free tier sufficient). Google Cloud account for GCS. Both 5-minute signups. |
| R15 | OAuth / API key restrictions deadline 2026-06-19 | **PRE-DEADLINE** | We ship today (2026-05-23). Restrict the key with IP allowlist anyway. |

**No hard drops.** Every concern has a tested or planned mitigation.

---

## 3. The Architecture Summary You Both Need to Know

The full architecture lives in `What_If_Master_Plan.md` (193 KB). For two-person co-build, internalise this much:

- **Two pipelines run concurrently.** Pipeline A is always-on perception (ingest → captions every 0.5 s → summary every 30 s → events → match-state → live commentary). Pipeline B is per-query counterfactual (resolve → direct → Veo → validate → compose).
- **12 agents** behind the gateway. They communicate over a bus; they never call each other directly. Their boundaries are in `What_If_Master_Plan.md` §5.
- **The trace store is a first-class subsystem.** Every model call, every tool call, every decision lands in the `trace_event` table with input/output blob references. The trace explorer in the frontend lets a judge click any clip and walk back to every frame, prompt, and model output.
- **Three external providers carry three loadbearing jobs.** GMI Cloud (reasoning + validator continuity + TTS), Google AI (deep video understanding + commentary voice + Veo video generation), RocketRide (the runtime that hosts all 12 agents as `.pipe` pipelines and Wave agents).

The diagram from the master plan:

```
       Frontend ──WS──► Gateway ──bus──► RocketRide Runtime ──► [12 agents]
                                                ▲   │
                                                │   ├── GMI Cloud (DeepSeek V4 Pro, Kimi K2.6, Qwen3-VL-235B, Inworld TTS)
                                                │   ├── Google AI (Gemini 3.5 Flash video, Live, Veo 3.1, Imagen 4)
                                                │   └── Postgres + pgvector + GCS + NATS
   YouTube Live HLS ────► IngestAgent ────► CaptureBuffer (chunks + frames)
                                                │
                                                └── TraceAgent ─► trace_event table ─► trace API ─► UI explorer
```

---

## 4. Division of Labor — you vs your teammate

You take the **deep technical surface**: the parts that need careful prompt design, real-time correctness, and direct API contact with the three providers. Your teammate (with Claude Code + agent teams) takes the **surrounding surface**: the gateway, the frontend, the share pages, the schemas, the infra glue. Everything below has a master-plan reference so neither of you has to think from scratch.

### YOU build — "Core perception + counterfactual brain"

| Module | Master plan reference | What to build |
|---|---|---|
| **YT live ingest (`agents/ingest/`)** | `What_If_Master_Plan.md` §16 (YouTube Live Ingest — Technical Implementation) | The `IngestSupervisor` class. `yt-dlp` URL resolution with `--remote-components ejs:github --js-runtimes node --cookies-from-browser chrome`. The ffmpeg tee command writing chunks + frames + archive. Watchdog file watcher. Postgres insert per chunk + per frame. Bus publish on `chunk.created` / `frame.created`. Reconnect supervisor with backoff. |
| **FrameCaptioner agent (`agents/captioner/`)** | §5 (Agents § FrameCaptionerAgent) + `prompts/captioner.system.md` | Subscribe to `frame.created`. Call Gemini 3.1 Flash Lite with image part + system prompt. Concurrency cap of 4 in-flight per session. Embed caption via `text-embedding-004`. Write `caption` row. |
| **Summariser agent (`agents/summariser/`)** | §5 + §4 (Pipeline A.A3) + `prompts/summariser.system.md` | 30-s tumbling window. Concat the window's chunks via ffmpeg into a single MP4. Call Gemini 3.5 Flash with the MP4 + structured-output JSON schema. Parse events. Auto-expand window on low confidence. |
| **MatchState agent (`agents/state/`)** | §5 (MatchStateAgent) | Deterministic transitions (goal → score++) plus GMI Kimi K2.6 for ambiguous deltas. Versioned row writes + Redis hot cache. |
| **Retrieval agent (`agents/retrieval/`)** | §5 + `prompts/retrieval.rerank.md` | Parse explicit timestamps. pgvector top-k. Gemini rerank with current match-state context. Clarification fork on low intent clarity. |
| **Director agent (`agents/director/`)** | §5 + `prompts/director.system.md` + `prompts/director.veo_schema.md` | The big prompt-engineering job. Compose the structured Veo brief from window context + match state. Reference-frame selection. |
| **VideoGen agent (`agents/videogen/`)** | §8 (Gemini + Veo integration, code samples) | `client.models.generate_videos` with `veo-3.1-fast-generate-preview` + reference images. LRO polling. Download to GCS the moment LRO completes (R7). |
| **Validator agent (`agents/validator/`)** | §5 + `prompts/validator.fidelity.md` + `prompts/validator.continuity.md` | Two parallel calls: Gemini 3.5 Flash watching the generated MP4 (fidelity), Qwen3-VL-235B on GMI comparing reference vs sampled clip frames (continuity). Verdict merge → ok/regenerate/reject with concrete reasons. |
| **Commentary agent (`agents/commentary/`)** | §5 + §8 (Gemini Live code sample) + `prompts/commentary.persona.md` | Gemini Live persistent session with 110-second rotation, audio-only-out + text-event-in. Stream tokens to gateway. |
| **The 9 prompt files** | `What_If_Master_Plan.md` §17 (verbatim) | Already in `prompts/`. Tweak as you go; commit changes. |
| **RocketRide `.pipe` pipelines** | §7 (RocketRide integration spec — has the node graphs and tool_pipe wiring) | `pipelines/perception.pipe`, `window_summariser.pipe`, `whatif.pipe`, `retrieval.pipe`, `veo_generation.pipe`, `validator.pipe`. Each is a JSON file the engine loads. |
| **Custom RocketRide nodes** | §7 (custom nodes list) | `youtube_ingest`, `llm_video_veo`, `pgvector_search`, `ffmpeg_compose`, `websocket_session_input`. These live under `nodes/src/nodes/`. |
| **Shared lib (`agents/_lib/`)** | §3 (data model) + §10 (provenance) | `trace.py` (span wrapper), `gmi.py` (OpenAI client w/ GMI base_url), `gemini.py`, `veo.py` (incl. `safe_reference_image()` for R9), `storage.py` (GCS), `bus.py` (NATS), `embeddings.py` (Gemini fallback). |

### TEAMMATE builds — "Everything around the brain"

Send them this exact list. They can fan it out to their agent teams.

| Module | Master plan reference | What to build |
|---|---|---|
| **Session Gateway (`services/gateway/`)** | §2 (Architecture), §11 (Frontend — WS protocol section) | FastAPI + WebSocket service. REST: `POST /api/sessions` (start), `POST /api/sessions/:id/queries`, `POST /api/sessions/:id/artifacts`. WS: `/ws/sessions/:id` with the typed envelope from §11. Auth via signed-cookie shim. Bridges to RocketRide engine via `rocketride.RocketRideClient` per §7 code sample. |
| **Postgres schema + migrations (`infra/migrations/`)** | §3 (Data Model — every table) | Alembic migrations for all tables: `session`, `chunk`, `frame`, `caption`, `summary`, `event`, `match_state`, `query`, `prompt`, `generation`, `clip`, `artifact`, `trace_event`, embedding tables. Plus `CREATE EXTENSION vector;`. |
| **Pydantic + TS domain models (`schemas/`)** | §3 | Pydantic models matching every table. Generate TS types from OpenAPI for the frontend. |
| **Frontend (`frontend/`)** | §11 (Frontend Architecture — every screen detailed) | Next.js 15 app. Landing → session view → trace explorer → director's-cut share page. WebSocket client. HLS player on the live canvas. Timeline scrubber with event chips. What-if composer with auto-suggested chips. Clip tray with in-flight progress + alt-reality overlay. Multi-user participant strip. All component shapes are in §11. |
| **Trace explorer UI** | §10 (Provenance — UI section) | Two-pane vertical tree + content viewer with renderer-per-kind. Wired to the trace API the gateway exposes. |
| **Sharing pages** | §12 (Shareable Artifacts) | `/c/<short_code>`, `/cut/<short_code>`, `/embed/c/<short_code>`. SSR with OG meta tags. Imagen 4 poster generated server-side. |
| **TraceAgent + read API (`agents/trace/`, `services/gateway/whatif_gateway/trace_api.py`)** | §10 (Provenance + Observability — full spec) | Batched inserts. Read API endpoints. Export ZIP with bundled `viewer.html`. |
| **Compositor agent (`agents/compositor/`)** | §5 (CompositorAgent) | Pure ffmpeg. Branch-card overlay, reel concat, HLS variant generation. |
| **Session agent (`agents/session/`)** | §5 (SessionAgent) | State machine, multi-user fan-out, query queue, rate limiting. |
| **Infra terraform (`infra/terraform/`)** | §13 (Infrastructure) | GCP project, GCS bucket, Cloud Run services, secret manager bindings, Neon project, Cloudflare DNS. |
| **Docker / Compose (`infra/docker/`, `infra/compose/`)** | §13 + §14 (Repo layout) | `Dockerfile`s for gateway, agent, ingest (with ffmpeg + yt-dlp + deno + node), nats. `docker-compose.dev.yaml` brings up postgres + nats + fake-gcs + redis. |
| **Setup agent (`agents/setup/`)** | §5 (SetupAgent) + `prompts/setup.match_meta.md` | One-shot match identification at session start. Gemini 2.5 Pro/Flash call. |
| **CI workflow (`.github/workflows/ci.yml`)** | §15 (Build team tasks T23) | Lint + typecheck + unit tests on PR. |
| **The contract** | This document + §3 + §10 | **The teammate writes against the schemas in §3 and the WS protocol in §11; they don't need to wait for the brain to be ready.** That's the whole point of the split. |

### Shared / talked about together

- The **bus event shapes** (`chunk.created`, `frame.created`, `summary.created`, `event.created`, `query.received`, etc.) — §5 (Agents § Communication) + §3.
- The **WS envelope** between gateway and frontend — §11.
- The **trace event shape** — §10.
- The **artifact short_code** format — §12.

Both of you commit to **the schemas in §3** and **the WS protocol in §11**. Once those are frozen everything else can be built in parallel without merge pain.

---

## 5. Day-of Execution Sequence

### T+0 (right now)

**You:**
```bash
# Get keys
open https://aistudio.google.com/apikey               # create GEMINI_API_KEY (enable billing!)
open https://console.gmicloud.ai                       # create GMI_API_KEY
# Pay $50 to GMI immediately for Tier 2 upgrade (24h lag).
# Email support@gmicloud.ai with hackathon team + ask for tier bump.

# Local tooling (Deno already installed via brew during verification)
deno --version
yt-dlp --version
ffmpeg -version | head -1

# Pull the repo
git clone https://github.com/ElijahUmana/What-If.git
cd What-If
```

**Teammate (parallel):**
```bash
# Get keys (separate Gemini key for the gateway is fine, or share)
# Provision Neon + GCS:
open https://neon.tech                                 # create Postgres + enable pgvector
open https://console.cloud.google.com/storage          # create bucket whatif-prod

# Clone + read
git clone https://github.com/ElijahUmana/What-If.git
cd What-If && less docs/02_ARCHITECTURE.md
```

### T+30 min — schemas frozen, both unblocked

Teammate finishes `infra/migrations/0001_init.sql` covering every table in §3 and pushes. Both of you now write against those types. Stop asking each other questions about field names from here.

### T+1 h — first end-to-end pixel

You: ingest agent running locally against the URL, chunks + frames landing in Postgres + GCS, captioner writing one row per frame.

Teammate: gateway + frontend skeleton up, WebSocket connecting, session view rendering with the (still empty) timeline.

### T+2 h — perception loop visible in UI

You: summariser firing, events appearing. Live commentary stream connected via Gemini Live.

Teammate: timeline scrubber populates with event chips; commentary panel scrolls.

### T+3 h — first what-if generated

You: retrieval + director + VideoGen end-to-end against a recorded test query. First validated clip lands in GCS.

Teammate: clip tray + alt-reality overlay wired; clicking a clip plays it.

### T+4 h — trace explorer

Teammate: trace API + UI navigable from a clip back to its frames.

### T+5 h — composer + sharing

Teammate: Director's Cut compositor, share landing pages.

You: harden the regeneration loop, the auto-expand summary, the validator.

### Demo prep T-1 h

- Three pre-built what-ifs to fire on demand (already-warmed Veo calls).
- One live what-if to do in front of judges.
- Trace explorer pre-opened on one clip ready to scroll.

---

## 6. Bootstrap commands the teammate runs immediately

```bash
# 1. Clone
git clone https://github.com/ElijahUmana/What-If.git
cd What-If

# 2. Read the master plan once. The relevant sections per task:
#    - Gateway:   docs/02_ARCHITECTURE.md, docs/11_FRONTEND.md (WS protocol)
#    - Schemas:   docs/03_DATA_MODEL.md
#    - Frontend:  docs/11_FRONTEND.md, docs/09_USER_FLOWS.md
#    - Sharing:   docs/12_SHARING.md
#    - Trace:     docs/10_PROVENANCE.md
#    - Infra:     docs/13_INFRA.md
#    - Repo:      docs/14_REPO_LAYOUT.md

# 3. Tooling
brew install ffmpeg deno
pip install --upgrade uv
uv venv && source .venv/bin/activate
uv pip install fastapi uvicorn websockets pydantic alembic psycopg[binary] pgvector \
               redis nats-py google-genai openai watchdog rocketride

# 4. Provision (free tiers fine)
#    - Neon Postgres @ neon.tech, enable pgvector
#    - GCS bucket whatif-prod @ console.cloud.google.com/storage
#    - Gemini key @ aistudio.google.com/apikey (enable billing!)
#    - GMI key @ console.gmicloud.ai

# 5. Local dev (after schemas land):
docker compose -f infra/compose/docker-compose.dev.yaml up -d postgres nats redis
uv run alembic upgrade head
uv run python -m services.gateway       # gateway
pnpm --filter ./frontend dev            # frontend
```

---

## 7. Boot the verified ingest now (copy-paste, runs immediately)

```bash
# Sanity smoke test on the demo URL, same as I just confirmed:
mkdir -p /tmp/whatif_smoke/{chunks,frames}
MANIFEST=$(yt-dlp \
  --remote-components ejs:github --js-runtimes node \
  --cookies-from-browser chrome \
  -f 300 -g "https://www.youtube.com/watch?v=ZS7-0zjC_rg" | head -1)

ffmpeg -y -t 60 -i "$MANIFEST" \
  -map 0:v -c:v copy \
    -f segment -segment_time 2 -segment_format mpegts -reset_timestamps 1 \
    /tmp/whatif_smoke/chunks/c_%03d.ts \
  -map 0:v -vf "fps=2,scale=1280:720" -q:v 4 \
    /tmp/whatif_smoke/frames/f_%05d.jpg

ls /tmp/whatif_smoke/chunks | head
ls /tmp/whatif_smoke/frames | head
```

You should see ~30 chunks and ~120 frames after 60 seconds. If you do, the ingest layer is good.

---

## 8. What we deliberately are NOT building today

- **Cluster Engine dedicated endpoint for embeddings.** Replaced by `text-embedding-004` for build day (R10). Plan stays in the master doc for production scale.
- **Imagen / Lyria nice-to-haves.** OG poster + share-page music bed are last-mile polish; if time runs out, the share pages still work without them.
- **Group-watch multi-user.** Architecturally supported (§9 Flow 2); we don't wire the participant strip + voting unless we have spare time.
- **Mobile layout.** Desktop demo; mobile in the master plan but not on the path.
- **Real-time HLS-into-Gemini.** Not supported by the API; we already pulled frames ourselves.

---

## 9. Demo Script (5 minutes)

1. *(0:00)* Open landing → paste the verified URL → land on the session view. Setup agent identifies "Valencia vs Barcelona, PES 21 simulation" within 3 s.
2. *(0:20)* Wait ~20 s. Live commentary panel starts streaming. Timeline scrubber starts populating event chips.
3. *(0:50)* Type: **"what if Lewandowski had shot first time instead of holding it"** (or whatever just happened). Show progress card cycling through Resolve → Direct → Generate → Validate.
4. *(1:30)* While that cooks, fire a pre-warmed what-if from a queue. Alt-reality overlay slides in beside the live match. Both play; live audio ducks.
5. *(2:30)* Click "Inspect trace" on the alt-reality clip. Trace explorer opens. Walk the tree: clip → generation → director → retrieval → the actual reference frames. Click a frame, it opens in the viewer.
6. *(3:30)* The original live what-if completes. Play it. Compare to the pre-warmed one.
7. *(4:00)* Hit "Director's Cut" → composed reel with branch cards. Show share link unfurls.
8. *(4:30)* Talk through what each of the three mandatory providers is doing in the trace tree, point at the model IDs in the explorer.
9. *(5:00)* Q&A.

---

## 10. Single source of truth

- This file = the two-person build plan.
- `What_If_Master_Plan.md` (193 KB on Desktop) = the full architecture every section is cross-referenced to.
- Repo = `https://github.com/ElijahUmana/What-If`.
- Source URL for the demo = `https://www.youtube.com/watch?v=ZS7-0zjC_rg` (verified live, non-DRM, 720p60 HLS).
