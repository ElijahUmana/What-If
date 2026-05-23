# What If — Master Architecture & Build Plan

*A real-time counterfactual viewer for live football, built on GMI Cloud, RocketRide, and Google Gemini + Veo.*

*Repo: `https://github.com/ElijahUmana/What-If`*

---

## Executive Summary

**What If** is a real-time multi-agent system that sits on top of a live YouTube football broadcast and lets the viewer ask **"what if?"** at any moment. The system has been watching the same broadcast they have — frame by frame, with continuously-indexed semantic memory — so it can resolve the moment they mean, pull real reference frames out of its own capture buffer, and use Veo 3.1 to generate the alternative reality as a video clip that visibly continues from the real moment with the same players, kit, stadium, and camera. The live match keeps playing the whole time. At full time the viewer walks away with a fully-provenanced shareable Director's Cut of their what-ifs.

The system is built on three mandatory technologies, each used in a load-bearing role:

- **GMI Cloud** carries reasoning (DeepSeek V4 Pro, Kimi K2.6), heavy continuity validation (Qwen3-VL-235B), and a dedicated H100 embeddings endpoint deployed with the `gmicloud` Python SDK.
- **RocketRide** is the agent runtime — `.pipe` pipelines drive 12 long-lived agents, with the Wave agent (`agent_rocketride`) as the planning loop and `tool_pipe` exposing sub-pipelines as composable tools.
- **Google Gemini + Veo** carries deep video understanding (`gemini-3.5-flash`), the conversational broadcast voice (`gemini-3.1-flash-live-preview`), and counterfactual video generation (`veo-3.1-generate-preview` with up to 3 reference images and native sync audio).

Three additional supporting capabilities round out the stack: **Imagen 4** for share-page OG posters, **Nano Banana 2** for character-consistent storyboard frames, and **Inworld TTS on GMI** for broadcast-grade commentary audio.

This document is the complete plan: vision, system architecture, data model, pipeline, agent topology, tech integration specs for each of the three mandatory technologies, user flows, provenance system, frontend, sharing, infrastructure, repo layout, build-team task decomposition, and the technical mechanics of the YouTube live ingest layer. Every prompt body the system uses is checked in.

There is no decorative AI in this system. Pull any of the three technologies out and the system loses a load-bearing component with no equivalent on any other platform today.

---

## Service & Model Allocation — single source of truth

| Function | Provider | Model / Endpoint | Why this one |
|---|---|---|---|
| Per-frame VL captioning (2 fps, all session) | Google AI | `gemini-3.1-flash-lite` (text+image) | Cheap, fast, generous free tier, native multimodal. |
| Buffered deep window summarisation (every 30 s) | Google AI | `gemini-3.5-flash` (video-in) | 1M context, native video, GA stable. |
| Deep-pass captioning on key frames | GMI Cloud | `Qwen/Qwen3-VL-235B-A22B-Instruct-FP8` | Frontier-class serverless VLM. |
| Live commentary voice + text stream | Google AI | `gemini-3.1-flash-live-preview` (Live API) | Bidirectional streaming with audio out. |
| Match state transitions | GMI Cloud | `moonshotai/Kimi-K2.6` | 256K context, strong structured-output. |
| Retrieval rerank | GMI Cloud | `moonshotai/Kimi-K2.6` | Long-context rerank quality. |
| Director (Veo brief composition) | GMI Cloud | `deepseek-ai/DeepSeek-V4-Pro` | 1M context, top reasoning. |
| Director (fast fallback) | GMI Cloud | `deepseek-ai/DeepSeek-V4-Flash` | ~12× cheaper, lower latency. |
| Counterfactual video generation (primary) | Google AI | `veo-3.1-generate-preview` | Reference-image conditioning + native audio. |
| Counterfactual video (fast path) | Google AI | `veo-3.1-fast-generate-preview` | 30–45 s latency. |
| Counterfactual video (budget) | Google AI | `veo-3.1-lite-generate-preview` | ~$0.03–0.05/sec. |
| Validator — fidelity (video-in) | Google AI | `gemini-3.5-flash` | Video-in unique to Gemini. |
| Validator — continuity (multi-image) | GMI Cloud | `Qwen/Qwen3-VL-235B-A22B-Instruct-FP8` | Multi-image input + 262K context. |
| Embeddings (timeline index) | GMI Cloud (dedicated) | `BAAI/bge-m3` on H100 via `gmicloud` SDK | GMI has no serverless embeddings; we deploy our own. |
| Embeddings (fallback) | Google AI | `text-embedding-004` | Hot fallback if dedicated endpoint is offline. |
| Match metadata one-shot | GMI Cloud | `zai-org/GLM-4.7` | Cheap structured output. |
| Commentary audio TTS | GMI Cloud | `inworld-tts-1.5-max` | Broadcast-grade voices, $0.01/req. |
| OG share-card poster | Google AI | `imagen-4.0-fast-generate-001` | $0.02/image, fast. |
| Storyboard reference frames (char-consistent) | Google AI | `gemini-3.1-flash-image-preview` (Nano Banana 2) | Up to 14 reference images. |
| Pipeline runtime + orchestration | RocketRide | Engine v3.2+ via `.pipe` files | Multi-tier runtime with C++ engine + Python nodes. |
| Agent planning loop | RocketRide | `agent_rocketride` (Wave) | Hierarchical agents via `tool_pipe`. |
| Stream capture | yt-dlp ≥ 2026.03.17 + ffmpeg 6.x | (subprocess) | Only stack that handles current YouTube PO-token challenges. |
| Compute (continuous capture) | RunPod RTX 4090 ($0.39/hr) | (Fly.io GPU sunsetting 2026-08-01.) | |
| Compute (AI bursts) | Modal | scale-to-zero functions | Burst budget. |
| Postgres + pgvector | Neon | managed | Timeline index + trace store. |
| Object storage | GCS | `whatif-prod` bucket | Chunks, frames, clips, exports. |
| Pub/sub fan-out | NATS JetStream + Redis Streams | self-hosted | Late-joiner replay. |
| Frontend hosting | Vercel | Next.js 15 | Native to the stack. |
| Auth | Clerk or NextAuth | hosted | Cookie-based sessions. |

Per-match cost envelope: **~$16/session** across all three providers (Gemini + Veo dominate; see `06_TECH_GMI_CLOUD.md` and `08_TECH_GEMINI_VEO.md` for breakdowns).

---

## Table of Contents

1. Vision
2. System Architecture
3. Data Model
4. End-to-End Pipeline
5. Agent Topology
6. GMI Cloud — Deep Integration Specification
7. RocketRide — Deep Integration Specification
8. Google AI (Gemini + Veo + Live + Imagen) — Deep Integration Specification
9. User Flows + UX Specification
10. Provenance + Observability
11. Frontend Architecture
12. Shareable Artifacts
13. Infrastructure
14. Repository Layout
15. Build Team Task Decomposition
16. YouTube Live Ingest — Technical Implementation
17. Prompt Library

---
