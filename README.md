<p align="center">
  <h1 align="center">What If</h1>
  <p align="center"><strong>What if we stopped asking what-ifs and started <em>seeing</em> what-ifs?</strong></p>
  <p align="center">
    Real-time counterfactual video generation for live football matches.<br/>
    Watch a match. Ask "what if?" at any moment. See the alternative reality — in video.
  </p>
</p>

---

## The Problem

Every football fan has said it: *"What if he'd passed instead of shooting?"* *"What if that free kick had curled in?"* Today, the answer is imagination. We built the answer in video.

## What We Built

**What If** is a real-time AI system that watches a football match alongside you — frame by frame, with continuous AI perception — and when you ask "what if?", it generates a video clip showing the alternative reality. Not a text description. Not a still image. **An actual video that continues from the real broadcast footage.**

The live match keeps playing. The what-if clip appears beside it. You can ask as many as you want. At full time, you walk away with a shareable reel of your counterfactuals.

| Feature | What It Does |
|---|---|
| **Real-time match perception** | Continuously analyzes frames at 2fps, detecting events (goals, shots, fouls, saves, corners) with structured semantic memory |
| **AI broadcast commentary** | Streams live text commentary grounded in what the AI actually sees — not hallucinated |
| **What-if video generation** | Resolves the moment you mean, composes a structured video prompt with visual continuity constraints, generates an 8-second counterfactual clip via Veo 3.1 |
| **Full provenance** | Every caption, every summary, every prompt, every generated frame is traceable from the final clip back to the source |

---

## Innovation

**No one has shipped this combination before:**

1. **Continuous multi-modal perception over a live video feed** with frame-precise temporal indexing queryable by natural language. Not post-hoc analysis — real-time, as the match happens.

2. **Reference-conditioned counterfactual video generation** where the output must be visually continuous with the source broadcast — same players, same kits, same stadium, same camera angle. Only the counterfactual changes.

3. **A system that stays in sync with reality while reality keeps moving.** The live match doesn't pause. The user keeps watching. The what-if renders in the background and appears alongside the broadcast.

This isn't "AI sports commentary" or "text-to-video." It's a perception-to-generation pipeline where the perception layer feeds the generation layer with real visual context from a live source, in real time.

---

## Deep Technology Integration

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              ROCKETRIDE RUNTIME                                 │
│                                                                                 │
│  ┌──────────────┐     ┌───────────────────┐                                     │
│  │ IngestAgent  │────►│ FrameCaptionerAgnt│────► Gemini 2.5 Flash (vision)      │
│  │ (yt-dlp +    │     │ (2fps structured  │                                     │
│  │  ffmpeg)     │     │  frame analysis)  │                                     │
│  └──────┬───────┘     └────────┬──────────┘                                     │
│         │                      │                                                │
│         │              ┌───────▼──────────┐                                     │
│         │              │ SummariserAgent  │────► Gemini 2.5 Flash (video-in)    │
│         │              │ (30s windows,    │     Native video understanding       │
│         │              │  event detection)│                                     │
│         │              └───────┬──────────┘                                     │
│         │                      │                                                │
│         │              ┌───────▼──────────┐                                     │
│         │              │ MatchStateAgent  │────► GMI Cloud (Kimi K2.6)          │
│         │              │ (score, period,  │     Structured state transitions     │
│         │              │  formations)     │                                     │
│         │              └───────┬──────────┘                                     │
│         │                      │                                                │
│         │              ┌───────▼──────────┐                                     │
│         │              │ CommentaryAgent  │────► GMI Cloud (DeepSeek V4 Flash)  │
│         │              │ (broadcast-style │     Live text commentary             │
│         │              │  AI commentator) │                                     │
│         │              └─────────────────┘                                     │
│         │                                                                       │
│         │   user asks "what if?"                                                │
│         │   ┌──────────────────┐                                                │
│         └──►│ RetrievalAgent   │────► GMI Cloud (DeepSeek V4 Flash)             │
│             │ (semantic moment │     Anchor resolution + reranking               │
│             │  resolution)     │                                                │
│             └────────┬─────────┘                                                │
│                      ▼                                                          │
│             ┌──────────────────┐                                                │
│             │ DirectorAgent    │────► GMI Cloud (DeepSeek V4 Flash)             │
│             │ (structured Veo  │     Prompt composition with visual context     │
│             │  brief composer) │     from captions + match state                │
│             └────────┬─────────┘                                                │
│                      ▼                                                          │
│             ┌──────────────────┐                                                │
│             │ VideoGenAgent    │────► Veo 3.1 (Google AI)                       │
│             │ (Veo 3.1 with   │     8-second counterfactual clips              │
│             │  reference imgs) │     with native sync audio                     │
│             └────────┬─────────┘                                                │
│                      ▼                                                          │
│             ┌──────────────────┐                                                │
│             │ ValidatorAgent   │────► Gemini 2.5 Flash (video-in)              │
│             │ (fidelity check: │     Watches the clip, verifies the             │
│             │  did the change  │     counterfactual occurred                    │
│             │  actually occur?)│                                                │
│             └──────────────────┘                                                │
│                                                                                 │
│  Pipeline orchestration: RocketRide agent_rocketride (Wave planning)            │
│  Model routing: RocketRide llm_gmi_cloud + llm_vision_gemini nodes              │
│  Memory: RocketRide memory_internal for agent state                             │
│  Observability: RocketRide native execution traces                              │
└─────────────────────────────────────────────────────────────────────────────────┘
         │                              │                           │
         ▼                              ▼                           ▼
┌─────────────────┐  ┌──────────────────────┐  ┌────────────────────────┐
│ Capture Buffer  │  │   Timeline Index     │  │   Provenance Store     │
│ (video chunks   │  │   (in-memory with    │  │   (trace events with   │
│  + raw frames)  │  │    semantic search)  │  │    blob refs to every  │
│ Local FS        │  │                      │  │    input & output)     │
└─────────────────┘  └──────────────────────┘  └────────────────────────┘
```

### GMI Cloud — The Reasoning Brain (5 distinct roles)

GMI Cloud isn't a wrapper — it's the reasoning engine behind every intelligent decision in the pipeline.

| Agent | GMI Model | Why GMI |
|---|---|---|
| **DirectorAgent** | DeepSeek V4 Flash | Composes structured Veo generation briefs from match context — needs 128K context for full caption history + match state |
| **RetrievalAgent** | DeepSeek V4 Flash | Resolves "what if that shot..." to exact PTS timestamp via semantic reranking over the event timeline |
| **MatchStateAgent** | Kimi K2.6 | Maintains structured game state (score, period, formations) with deterministic transitions + LLM for ambiguous deltas |
| **CommentaryAgent** | DeepSeek V4 Flash | Generates broadcast-quality live commentary grounded in perception layer output |
| **ValidatorAgent** (continuity) | DeepSeek V4 Flash | Cross-checks visual consistency between generated clips and source frames |

**Why GMI specifically:** Per-token cost allows us to run 5 reasoning agents continuously for 90 minutes without budget anxiety. OpenAI-compatible API means zero migration cost if we scale. H100/H200 fleet means sub-second inference on DeepSeek V4 Flash.

### RocketRide — The Agent Runtime

RocketRide is the substrate the entire multi-agent system runs on — not a thin wrapper.

**Pipeline definitions** (`.pipe` files):
- `whatif-director.pipe` — `agent_rocketride` (Wave planning, 5 waves) → `llm_gmi_cloud` (DeepSeek V4 Flash) → `memory_internal` → `response_answers`
- `perception.pipe` — `dropper` → `frame_grabber` → `llm_vision_gemini` → `agent_rocketride` (summariser)

**What we use from RocketRide:**
- `agent_rocketride` — Wave planning loop with tool composition for the Director agent
- `llm_gmi_cloud` — Native GMI Cloud model routing (no OpenAI-compat shim needed)
- `llm_vision_gemini` — Native Gemini vision model routing
- `memory_internal` — Agent state persistence across waves
- `chat` source — SDK-driven query intake
- Pipeline-as-tool via `tool_pipe` — Sub-pipeline composition for retrieval

**SDK integration:**
```python
from rocketride import RocketRideClient, Question

client = RocketRideClient(uri=f'ws://localhost:{engine_port}')
await client.connect('local')
result = await client.use(pipeline=pipe_config)
token = result['token']

# Route what-if reasoning through RocketRide → GMI Cloud
response = await client.chat(token=token, question=Question(text=query))
```

**Why RocketRide specifically:** Long-lived multi-agent pipelines with heterogeneous model routing (GMI + Gemini in the same graph), native observability, and the Wave planning loop that lets the Director iterate on Veo briefs across multiple reasoning waves.

### Google AI (Gemini + Veo) — Perception + Generation

Three distinct Google capabilities carry three distinct jobs:

| Capability | Model | Role | Why Only Google |
|---|---|---|---|
| **Frame captioning** | Gemini 2.5 Flash | Per-frame structured analysis at 2fps | Native multimodal with 1M context, sub-second latency |
| **Video summarisation** | Gemini 2.5 Flash | 30-second window analysis with native video input | Only model that accepts raw video bytes with structured output |
| **Match identification** | Gemini 2.5 Flash | One-shot team/kit/stadium detection from opening frames | Multimodal reasoning over multiple images |
| **Fidelity validation** | Gemini 2.5 Flash | Watches generated clip, verifies counterfactual occurred | Video-in capability unique to Gemini |
| **Counterfactual video** | Veo 3.1 | 8-second clips with reference-image conditioning | Only model with reference frames + native sync audio |

**Pull any of these three technologies out and there is no system left.** GMI carries reasoning, RocketRide carries orchestration, Google carries perception and generation.

---

## Impact

### For Fans
A new form of entertainment layered on top of the match they're already watching. Not a replacement for the broadcast — an augmentation. Every missed chance, every controversial decision becomes explorable.

### For Broadcasters
A production tool: generate alternative-outcome clips in near-real-time during live broadcasts. "What if VAR had overturned that?" with a generated video showing the alternative, ready to broadcast.

### For Social
Shareable what-if reels that go viral. "My what-if reel from the Champions League final" — each clip tagged with the real moment it branched from, fully provenanced.

### The Market
The global football audience is **5 billion**. Live match engagement is the single highest-value moment in sports media. What If adds a second screen experience that keeps fans engaged for 90+ minutes while generating shareable content that extends engagement well beyond the final whistle.

---

## Execution

### What's Built and Working

- **12 specialized AI agents** running in a coordinated pipeline
- **Real-time frame capture** at 2fps from any YouTube football match (720p H.264)
- **Continuous perception loop** producing structured events, summaries, and commentary every 45 seconds
- **AI broadcast commentary** that reads like a real commentator: *"GOAL! Liverpool take the lead. Number 20 makes a sharp move inside the box and slots it home. That's a composed finish under pressure."*
- **End-to-end what-if pipeline**: user query → moment resolution → Veo brief composition → video generation → fidelity validation → playable clip in the UI
- **Live frontend** with YouTube embed, scrolling commentary, timeline scrubber with event chips, what-if composer with suggestion chips, and clip tray with generation progress
- **Verified**: Gemini captions ✓, GMI reasoning ✓, Veo generation (8s clips, ~60-90s latency) ✓, RocketRide pipeline execution ✓

### Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, TypeScript, Tailwind CSS, Zustand |
| Gateway | FastAPI, WebSocket (bidirectional event streaming) |
| Agent Runtime | RocketRide Engine (C++ core, Python nodes) |
| Perception Models | Gemini 2.5 Flash (vision + video-in) |
| Reasoning Models | GMI Cloud DeepSeek V4 Flash, Kimi K2.6 |
| Video Generation | Veo 3.1 (reference-conditioned, native audio) |
| Ingest | yt-dlp + ffmpeg (HLS → 2s segments + 2fps frames) |
| State | In-memory (production: Postgres + pgvector) |

### Repo Structure

```
What-If/
├── agents/                 # 12 AI agents
│   ├── ingest/            # YouTube capture pipeline
│   ├── captioner/         # Per-frame Gemini vision
│   ├── summariser/        # 30s window video analysis
│   ├── retrieval/         # Semantic moment resolution
│   ├── director/          # Veo brief composition
│   ├── videogen/          # Veo 3.1 generation
│   ├── validator/         # Fidelity + continuity checks
│   ├── commentary/        # AI broadcast commentary
│   ├── setup/             # Match identification
│   └── _lib/              # Shared: gemini, gmi, veo, trace
├── pipelines/             # RocketRide .pipe definitions
├── prompts/               # 9 versioned prompt bodies
├── services/gateway/      # FastAPI + WebSocket + orchestrator
├── frontend/              # Next.js app
├── schemas/               # Pydantic domain models
└── docs/                  # Full architecture (17 documents)
```

---

## Quick Start

```bash
git clone https://github.com/ElijahUmana/What-If.git
cd What-If

# Set API keys
echo "GEMINI_API_KEY=your-key" > .env
echo "GMI_API_KEY=your-key" >> .env

# Install
pip install google-genai openai watchdog python-dotenv ulid-py Pillow
cd frontend && pnpm install && cd ..

# Run
uvicorn services.gateway.main:app --port 8000 &
cd frontend && pnpm dev &

# Open http://localhost:3000, paste any YouTube football match URL
```

---

## Team

Built at the **Google I/O Kickoff: Pre-World Cup Hack** (May 23, 2026) in San Francisco.

---

<p align="center">
  <strong>What if we stopped asking what-ifs and started seeing what-ifs?</strong>
</p>
