# Provenance + Observability

The user asked for this explicitly: every artifact in the system must be traceable end-to-end. You should be able to click a finished clip and walk backwards through every model call, every retrieved frame, every summary, every caption, every chunk that contributed to it. This document is the spec for how that works.

## Goals

1. **Replayable.** Given a trace, the system can re-run any individual step with the same inputs and verify the output.
2. **Navigable.** A human can walk a trace top-down (from a finished clip) or bottom-up (from a single frame to every artifact that ever referenced it).
3. **Dynamically expandable.** If a node references "the surrounding window," expanding it reveals the actual frames and captions in that window. Nothing is summarised away.
4. **Exportable.** The full provenance for a session (or just for one clip) can be packaged into a ZIP with every artifact and a manifest.
5. **Free of cost-blockers.** Trace persistence must not block production traffic. It is best-effort with local buffering.

## The trace event

A single trace event is a node in a directed acyclic graph. Edges are `parent_id` references.

```json
{
  "id": "tr_01HXYZ…",
  "session_id": "ss_…",
  "agent": "DirectorAgent",
  "kind": "model_call",
  "parent_id": "tr_01HXYW…",
  "started_at": "2026-05-23T14:24:11.045Z",
  "ended_at": "2026-05-23T14:24:13.211Z",
  "status": "ok",
  "input_ref": {
    "kind": "blob",
    "blobs": [
      {"uri": "gs://…/frames/00000098765.jpg", "role": "ref_frame_0"},
      {"uri": "gs://…/frames/00000098770.jpg", "role": "ref_frame_1"},
      {"uri": "gs://…/inline/tr_01HXYZ_prompt.json", "role": "prompt_body"}
    ]
  },
  "output_ref": {
    "kind": "blob",
    "blobs": [
      {"uri": "gs://…/inline/tr_01HXYZ_output.json", "role": "structured_prompt"}
    ]
  },
  "model_id": "gemini-2.5-pro",
  "latency_ms": 2166,
  "payload": {
    "purpose": "compose_veo_prompt",
    "anchor_event_id": "ev_…",
    "anchor_pts_ms": 1452045
  }
}
```

Notes:
- `input_ref` and `output_ref` are **content-addressed pointers** to artifact storage. They are never the raw payload (which can be large). The trace is small and queryable; the artifacts live in object storage and are pulled on demand by the trace UI.
- `payload` is a small structured tag describing what this node *was* doing — used for UI labelling and quick filtering.
- The chain `parent_id` walks up to the original user query (which itself has parent = the session start).

## Event kinds

- `agent.lifecycle` — open/close of an agent's overall handler.
- `model_call` — a single external model invocation.
- `tool_call` — invocation of a deterministic tool (ffmpeg, retrieval, etc.).
- `state_write` — a write to the index or match-state.
- `decision` — a branching choice the agent made (e.g. "regenerate=true because validator flagged kit colour drift").
- `error` — a captured failure (with stack trace stored in a blob).
- `pubsub.in` / `pubsub.out` — bus events received/emitted.

Every span MUST have one kind. Kinds are not freeform.

## Tree examples

### From a finished clip
```
clip cl_456
└── compose tool_call (ffmpeg concat)
    └── validate decision (verdict=ok)
        ├── validate model_call (Gemini fidelity)
        ├── validate model_call (GMI VL continuity)
        └── generation
            └── generate tool_call (Veo LRO submit)
                └── direct model_call (Gemini compose prompt)
                    ├── retrieval decision (anchor=ev_123)
                    │   ├── retrieve tool_call (pgvector search)
                    │   ├── retrieve model_call (Gemini rerank)
                    │   └── retrieve state_write (query.parsed)
                    └── (refs: frame fr_X, fr_Y, fr_Z, summary sm_W, event ev_123)
```

### From a single frame
```
frame fr_X
└── caption model_call (GMI VL)
    └── summary model_call (Gemini video-in)
        └── event detected (ev_123)
            └── … (every downstream what-if that ever cited this frame)
```

We support both views in the UI.

## Storage strategy

- The `trace_event` table holds the spans (small rows).
- Bulky inputs/outputs are written to a sibling object-store prefix: `gs://whatif-{env}/sessions/{session_id}/inline/tr_…`.
- Frames, chunks, generated clips, and reference frames are already in their normal paths; the trace just references them.

## Read API

The session gateway exposes a read API on top of the trace store:

```
GET  /api/sessions/:id/trace/root                 → the root span for the session
GET  /api/sessions/:id/trace/:trace_id            → a single span
GET  /api/sessions/:id/trace/:trace_id/children   → immediate children
GET  /api/sessions/:id/trace/:trace_id/descendants?depth=N
GET  /api/sessions/:id/trace/by-artifact?clip_id=…
GET  /api/sessions/:id/trace/by-frame?frame_id=…  → reverse lookup
GET  /api/sessions/:id/trace/export                → returns a signed ZIP URL
```

All endpoints return JSON with stable shapes documented in `schemas/trace.openapi.yaml`.

## Write path

- Agents emit trace events via the RocketRide trace SDK we wrap (`agents/_lib/trace.py`). The wrapper:
  1. Allocates a ULID for `id`.
  2. Captures `started_at` immediately.
  3. Captures `ended_at` when the wrapped block exits.
  4. Persists `input_ref` and `output_ref` blobs to object storage before flushing the row.
  5. Sends the row to a local in-process buffer (max 256 rows or 1 s, whichever first).
  6. Buffer flushes to Postgres in batches.
- If Postgres is unreachable, the buffer spills to a local on-disk WAL (newline-delimited JSON). A background goroutine drains the WAL.

## Replay

Given any `trace_event`, the system can replay it:
- For `model_call` spans, the inputs are fully captured. We re-invoke the same model with the same inputs and diff the output.
- For `tool_call` spans, the inputs (e.g. ffmpeg arg list) and the input artifacts (e.g. source chunks) are captured. Re-running produces byte-identical outputs in practice.

Replay is a button in the trace explorer ("re-run this step"). The result lands in a sibling span tagged `replay_of=<original>`.

## Dynamic context expansion

The user asked for this explicitly: a node tied to a 30 s window can be expanded to a 60 s or 90 s window with no loss of fidelity.

- Every summary span carries the window boundaries.
- Expanding a summary in the trace explorer triggers a `replay_with` action: the summariser is re-run with a wider window. The new summary span is shown side by side with the original.
- Expanding a retrieval span shows the next 10 candidates beyond the top-20.
- Expanding a generation span shows the polling timeline and any intermediate Veo previews if available.

The UI never hides depth. Anything that can be expanded shows an explicit chevron with the cost ("expanding will re-invoke the summariser model, ~1.5 s, ~$0.003"). The judge can drill into the raw atoms.

## What the trace explorer looks like (concrete)

A two-pane vertical tree on the left, an artifact viewer on the right. Tree nodes show: icon for agent, span title, model ID, latency, status. Right-pane is contextual:
- A model_call span shows: full prompt (formatted), full response (formatted), all reference inputs (rendered: images as images, JSON as syntax-highlighted, video as inline player).
- A tool_call span shows: command line, stdout/stderr, output artifacts.
- A decision span shows: the inputs that led to the choice, the choice itself, the rule that fired.
- A state_write span shows: the row diff (before / after).
- An error span shows: full traceback, the request that triggered it, suggested re-run with adjusted inputs.

## Observability for the operator

Beyond the user-facing trace explorer, the same data feeds a small operator console:
- Per-agent QPS, p50/p99 latency, error rate.
- Backlog depth for each subscription.
- Veo LRO queue depth and wait time.
- Cost per session (computed from `model_call.payload` + a tiny model-price table).
