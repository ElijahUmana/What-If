# User Flows + UX Specification

## Personas

1. **Solo viewer** — watching a match alone, wants extra entertainment. Issues 3–10 what-ifs across the match. Wants a personal reel at the end.
2. **Group watch** — 2–6 friends watching together (each on their own device), sharing one session. Each can issue what-ifs that the whole group sees. The group walks away with a shared director's cut.
3. **Judge / explorer** — opens a shared session link after the fact. Watches the director's cut; clicks any clip to inspect provenance; rabbit-holes into individual model calls.

All three are first-class. Architecture, persistence, and sharing all assume these three modes from the ground up.

---

## Flow 1 — Session start (solo)

### Screen S1.0 — Landing
- Brand mark. One sentence: "Ask what if about a live football match. Get the answer in video."
- Primary action: a single input — "Paste a YouTube live URL."
- Secondary action: "Join a friend's session" with a session code field.

### Screen S1.1 — Stream verify
- Server validates the URL is a live YouTube stream. Resolves the manifest in the background.
- The setup agent fires; identified match metadata returns within 3 s.
- The page shows: identified teams + competition + kickoff time. "Looks right?" with a confirm / edit button.

### Screen S1.2 — The session view (the main canvas)
Layout (1920×1080 reference):
- **Top bar:** match meta (teams, score, period clock pulled from `match_state`), "Invite" button, "Director's Cut" button (greyed until first clip exists).
- **Main canvas (left ⅔):** live YouTube player. Underneath: the timeline scrubber. Above the scrubber, a row of detected event chips (goal / chance / card / sub). Hovering a chip shows the one-line caption; clicking it scrolls a context tooltip with the buffer summary.
- **Right column (⅓):**
  - **Top:** Live AI Commentary — streaming text from the CommentaryAgent. Auto-scrolling. Pinning a line saves it to the session.
  - **Middle:** The what-if composer. Text input plus suggested chips (auto-derived from recent events: "what if [striker] had shot first time?" type suggestions, regenerated as the match evolves).
  - **Bottom:** The clip tray — every validated what-if appears as a card with thumbnail, prompt, and a play button. Cards include a "branch" button that prefills the composer for a follow-up what-if from this clip.

### Screen S1.3 — What-if in progress
- When a query is submitted, a progress card slides into the clip tray with five mini-stages: Resolve → Direct → Generate → Validate → Ready.
- Each stage shows live state and the input/output of that stage (clickable to peek into the trace).
- The live player keeps playing the whole time. Audio is on. The user is not interrupted.

### Screen S1.4 — What-if ready
- Card flips to a thumbnail + play button.
- Clicking the thumbnail opens an alt-reality viewer overlaid on the right side of the page. Live match keeps playing in the main canvas at a lower volume; alt-reality plays in the overlay at full volume.
- The overlay header shows: "Branched from [event] at [clock]." with a "view trace" link.
- The user can branch from the clip ("now what if this had happened instead..."), share the clip directly, or close.

---

## Flow 2 — Group watch

### Screen S2.0 — Invite
- The owner of a session clicks "Invite" → modal with a 6-char join code and a shareable URL.
- Friends paste the URL in their own browsers, land on S1.0 with the code prefilled.

### Screen S2.1 — Joined view
- Identical to S1.2, but the right column shows a participant strip at the top: avatars of who's connected.
- Each what-if card shows which participant asked it. Each card's branch action is allowed by anyone.
- A small "raise hand" / "react" set of micro-interactions on each card so the group can vote on which clips make the director's cut.

### Screen S2.2 — Final director's cut (group)
- At full time (or whenever the owner clicks "End session"), the compositor produces the group director's cut. Voting determines clip order: top-voted first.
- Result is a single MP4 with title card naming all participants.
- A share URL is generated for the artifact.

---

## Flow 3 — Provenance exploration (judge / explorer)

### Screen S3.0 — Shared session
- User opens `https://whatif.app/s/<short_code>`.
- Sees the director's cut prominently. Below it: a "How this was made" expansion.

### Screen S3.1 — Director's Cut viewer
- A polished player. Each clip in the reel is annotated with a strip below the player containing:
  - The user prompt that produced it.
  - "Branched from" event chip linking to the source moment.
  - "Inspect" button.

### Screen S3.2 — Clip inspector (the trace explorer)
- Two-pane: left pane shows a vertical tree of the clip's provenance; right pane shows whatever the user clicked in the tree.
- The tree, top to bottom for a clip:
  - **The clip** — final MP4 (playable).
    - **Generation** — Veo prompt body (verbatim), reference frames (clickable thumbnails), Veo response metadata, latency, model ID.
      - **Direction** — director's reasoning, the chosen reference frames, the structured prompt build steps.
        - **Retrieval** — the user text, the parsed timestamp, the top-20 retrieved candidates with similarity scores, the LLM rerank reasoning.
          - **Index** — the captions and summaries the retrieval was over, click to see the underlying frames.
    - **Validation** — both validator outputs, the verdict, the regeneration if any.
- Every node shows: the model used, input bytes, output bytes, latency, status.
- Every input/output is downloadable as raw artifact (JSON, JPG, MP4).

### Screen S3.3 — Frame archive view
- An auxiliary screen accessible from any caption in the trace explorer.
- Shows the broadcast as a scrubbable mosaic of frames at 1 fps. Hovering a frame surfaces its caption, its parent chunk, its summary buffer.
- Used to verify "the system actually saw what it claims it saw."

---

## Flow 4 — Edge experiences

### Stream lost mid-match
- The session UI shows a non-blocking banner "Stream reconnecting…" while ingest backs off.
- Already-captured content is fully available; queries that target moments before the drop work normally.
- When the stream returns, the timeline shows a gap labelled "no signal" — clicking it explains what happened.

### Veo generation fails for a clip
- The clip card transitions to an error state with a structured message: "Veo couldn't generate this — the moment was ambiguous. Try one of these refinements:" with three concrete suggested rewrites produced by the director agent.

### User asks something the system can't anchor
- Retrieval returns clarification candidates. The composer expands inline with two or three "did you mean…?" chips. Selecting one re-submits the query.

### User asks for something off-topic
- E.g. "what if a giraffe was the keeper" — DirectorAgent flags it as not a counterfactual on a real event; UI shows a soft refusal with explanation and suggests rephrasings rooted in real moments.

### Multiple in-flight queries
- The clip tray shows all in-flight progress cards in queue order with position indicators. The user is never blocked from issuing more.

### Branching from a generated clip
- The follow-up what-if treats the clip's final state as the new anchor; retrieval skips the index and uses the clip's metadata directly. The trace explorer shows the branch tree.

---

## Component-level UX details

### The what-if composer
- A single text input with `Enter` to submit.
- Below the input, three auto-generated chip prompts updated every 30 s as new events arrive. Examples:
  - After a near-miss: "what if that had gone in?"
  - After a sub: "what if [outgoing player] had stayed on?"
  - After a foul: "what if the ref had played advantage?"
- Right-clicking any event chip on the timeline scrubber populates the composer with a structured prompt scaffolded around that event.

### The clip tray
- Cards are ordered newest-first while in-progress, then by user re-order ("Pin to top," drag to reorder).
- Each card has a 3-dot menu: Play / Branch / Share / Inspect Trace / Remove from director's cut.

### The live commentary panel
- Each commentary line is timestamped at its source-stream pts.
- Clicking a line snaps the timeline scrubber to that moment and shows the frames in a small preview.
- A "translate" toggle uses Gemini Live to deliver the commentary in a chosen language live.

### The timeline scrubber
- Spans from kickoff (left) to "live now" (right edge, growing).
- Event chips coloured by type.
- A vertical "now" line pulses live.
- Right-clicking anywhere on the scrubber pulls up "ask a what-if anchored here."

### Mobile layout
- Single column. Live player at top. Commentary and what-if composer collapse into tabs below.
- Alt-reality clips open full-screen with swipe-down to return.

---

## State diagram (session)

```
init ──► resolving_match ──► ingesting ──► live ──► (user requests) live
                                            │           │
                                            │           ▼
                                            │    query_in_flight
                                            │           │
                                            ▼           ▼
                                       full_time ──► closing ──► closed (artifact created)
```

## State diagram (query)

```
received ──► resolving ──► resolved ──► directing ──► generating ──► validating ──► ready
                                                                          │
                                                                          ▼
                                                                     regenerate ──► generating
                                                                          │
                                                                          ▼
                                                                       rejected
   any ──► clarification_needed ──► (user selects) ──► resolving
```

Every transition emits a UI event so the progress card and clip tray reflect state in real time.
