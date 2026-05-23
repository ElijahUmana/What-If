# Frontend Architecture

The frontend is a single-page Next.js application (App Router) that talks to the session gateway via REST + a single WebSocket per session. It is intentionally thin: the gateway is the source of truth.

## Stack

- **Next.js 15** (App Router, React 19 server components for static surfaces, client components for the live session view).
- **TypeScript** strict.
- **Tailwind CSS** + shadcn/ui for components.
- **Zustand** for client state.
- **TanStack Query** for REST cache + invalidation.
- **react-hls.js** for the live YouTube playback (via the resolved manifest from the server) — falls back to native iframe embed when DRM-restricted.
- **react-player** for alt-reality clip playback.
- **mp4box.js** for client-side trimming and merging on the timeline scrubber preview.
- **D3** for the timeline scrubber rendering.

## Routes

- `/` — landing.
- `/s/[short_code]` — join session by code.
- `/session/[id]` — the main session view (live).
- `/session/[id]/trace/[trace_id]` — deep link into the trace explorer.
- `/cut/[short_code]` — public director's-cut page (no session login required).

## State model

```ts
type SessionState = {
  session_id: string;
  match_meta: MatchMeta;
  match_state: MatchState;
  commentary: CommentaryLine[];          // streamed
  events: TimelineEvent[];               // streamed
  queries: QueryProgress[];              // streamed
  clips: Clip[];                          // streamed
  participants: Participant[];
  ingest_status: IngestStatus;
};
```

All of these populate from a single WebSocket event stream. The frontend never polls.

## WebSocket protocol

Server → client envelope:
```json
{ "type": "match_state.update", "payload": { … } }
{ "type": "commentary.line",   "payload": { "text": "…", "pts_ms": 1452045 } }
{ "type": "event.created",     "payload": { … } }
{ "type": "query.progress",    "payload": { "query_id": "qr_…", "stage": "validating" } }
{ "type": "clip.ready",        "payload": { "clip_id": "cl_…", "uri": "…" } }
{ "type": "ingest.status",     "payload": { "status": "reconnecting" } }
```

Client → server:
```json
{ "type": "query.submit", "payload": { "text": "…", "anchor_pts_ms": 1452045 } }
{ "type": "clip.branch",  "payload": { "parent_clip_id": "cl_…", "text": "…" } }
{ "type": "clip.pin",     "payload": { "clip_id": "cl_…" } }
{ "type": "directors_cut.request" }
```

All payloads validated by Zod schemas shared from `schemas/ws.ts`.

## Component tree (session view)

```
<SessionLayout>
  <TopBar match={match_meta} score={match_state.score} clock={match_state.clock} />
  <main>
    <PlayerCanvas>
      <LiveHLSPlayer src={manifest_url} controls />
      <TimelineScrubber events={events} liveAt={now} />
      <AltRealityOverlay open={...} clip={...} />
    </PlayerCanvas>
    <SidePanel>
      <ParticipantStrip participants={participants} />
      <CommentaryStream lines={commentary} />
      <WhatIfComposer onSubmit={...} suggestions={derivedSuggestions} />
      <ClipTray clips={clips} inFlight={queries} />
    </SidePanel>
  </main>
  <FooterBar
    actions={[InviteButton, DirectorsCutButton, EndSessionButton]}
  />
</SessionLayout>
```

## The live player

- The gateway returns the resolved HLS manifest URL. The client plays it directly via hls.js.
- When a what-if completes, the live player remains in the main canvas but its volume ducks to 20% while the alt-reality overlay plays. Returning to live restores volume.
- The live player's current time is synced to the timeline scrubber. The `pts_ms` of the current frame is reported back to the gateway as a heartbeat (used for the "anchor here" right-click action).

## The timeline scrubber

- Renders left-to-right from kickoff to live edge.
- Event chips coloured by `event.type`.
- Hover: tooltip with the one-line caption + thumbnail.
- Right-click: opens a small contextual menu — "Ask what if anchored here," "Show frames at this moment," "Inspect summary."
- Live edge pulses; the scrubber grows continuously as new chunks arrive.

## The what-if composer

- Single-line input. Submit on Enter or button click.
- Below the input: three "suggestion chips" rotated every 30 s, derived by a lightweight client-side LLM call (Gemini Flash via the gateway) seeded from the last two events.
- Composer optionally remembers a `parent_clip_id` if you came from "branch this clip" — the input is prefilled with "Now what if…" and the parent context is bound to the submission.

## The clip tray

- Each clip is a card: thumbnail (first frame), prompt, branch_count badge, status badge.
- In-progress queries appear as cards with the 5-stage progress mini-bar.
- Drag to reorder for director's-cut sequence. Star to pin to top. Trash to remove from cut (but never deleted from session record).

## The alt-reality overlay

- Slides in from the right, takes ~⅓ of the viewport.
- Header: "Branched from [event] at [clock]" + close + maximise + share + inspect-trace.
- Single player. Looped autoplay by default.
- Below the player: the user prompt and a "branch from this clip" action.

## The trace explorer

- Route: `/session/[id]/trace/[trace_id]`.
- Two-pane vertical layout: tree on left, content viewer on right.
- Tree built incrementally — only loaded children are shown; expand reveals next level.
- Content viewer chooses renderer by `kind`:
  - `model_call`: `<PromptViewer>` + `<ResponseViewer>`, both with raw/pretty toggle.
  - `tool_call`: `<CommandLine>` + `<StdioPanel>` + `<ArtifactList>`.
  - `decision`: `<DecisionViewer>` showing inputs/rule/output.
  - `state_write`: `<DiffViewer>` (before/after).
  - `error`: `<ErrorPanel>` (traceback + retry button).
- Every artifact reference is clickable; clicking a frame URI opens the frame inline.

## Director's-cut page

- Public route, no auth.
- Hero: video player playing the final cut.
- Below: a chip strip — one chip per clip in the cut. Clicking a chip seeks the player and shows that clip's prompt + branched-from info + "Inspect trace" button.
- "How this was made" expander reveals the trace tree for the whole cut.
- Share buttons (copy link, Twitter, Bluesky, WhatsApp).

## Performance

- The live WebSocket carries on the order of 1 event/sec on average. Negligible.
- Commentary stream is text. No throttling needed for any reasonable network.
- Reference frames are loaded lazily as the user interacts with the timeline or the trace.
- Generated clips are streamed via HLS via a short transcode (the compositor produces an HLS variant alongside the source MP4 for instant playback).

## Accessibility

- All controls keyboard-reachable. The what-if composer focuses on `?`.
- Live commentary is also rendered into ARIA live regions so screen readers narrate the match.
- Captions on every clip (auto-generated by the validator's transcription pass).

## Offline behavior

- A session in `closed` state is fully replayable from cache. The director's-cut page works without a backend (all artifacts are public-readable via signed URLs).
