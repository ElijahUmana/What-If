# What If — Vision

## The product in one paragraph

**What If** turns a live football broadcast into a *branchable timeline*. You watch the match as it happens. At any moment — a missed shot, a bad call, a controversial sub — you ask "what if?" The system has been silently watching the same broadcast you are, frame by frame, indexing every event with timestamped semantic memory. It picks out the exact 30–120 second window your question is about, reconstructs the scene from real reference frames pulled out of its continuous capture buffer, and uses a state-of-the-art video generation model to render the alternative reality as a clip that visibly continues from the real moment with the same players, same kit, same stadium, same camera angle — only the chosen variable changed. The live match keeps playing. The alternate continuation pops up beside it. You can branch from a branch. At full time you walk away with a shareable "director's cut" reel of your timeline of what-ifs, fully provenanced from frame to final pixel.

## Why this is hard and why it's worth building

Most "AI sports" demos do one of two things: (1) generate post-hoc commentary on a finished video, or (2) generate a single decontextualised video clip from a text prompt. Both are toys. This system has to do three things at once that nobody has shipped together at the level we are shipping them:

1. **Run a continuous multi-modal perception loop over a live broadcast** with frame-precise temporal indexing, where the index is *queryable by natural language* against any moment in the stream's lifetime — not a fixed window, not a single snapshot.
2. **Generate counterfactual video that is visually continuous with the real match.** The kit colours, the player positions, the stadium dressing, the broadcaster's overlay style — all must be inherited from the source frames, not invented. The change must be *only the counterfactual* the user asked for. This is reference-conditioned video generation driven by an agentic prompt composer, not naked text-to-video.
3. **Stay in sync with reality while reality keeps moving.** The live broadcast does not pause. The user is watching it. The what-if is rendered, contextualised, and presented without disrupting the live experience. The whole thing has to keep up.

Everything in this system serves those three jobs. There is no decorative AI. There is no "we also added a chatbot." Every model call earns its place by either advancing the perception loop, resolving a user query against the timeline, or producing/validating the counterfactual.

## Required technology — and why each is load-bearing

Three technologies are mandatory for the hackathon. We use each one in a place where it is the right answer, not as a sticker on the side of the box.

- **GMI Cloud** carries the **real-time perception layer**: high-QPS vision-language frame captioning, embedding generation for the timeline index, and a fast reasoning model for the live commentary stream. This is exactly the workload H100/H200 inference is built for — many small calls per second across the whole match. A single API outage on this layer would blind the whole system, so it has to be fast, cheap per call, and OpenAI-compatible so we can swap models without a rewrite. GMI is the only vendor on stage today that fits all three.
- **RocketRide** is the **agent runtime**. The system is not a script; it is a long-lived multi-agent service where a dozen specialised agents talk to each other over the lifetime of a 90-minute match — ingest workers, captioners, summarisers, a match-state tracker, a retrieval agent, a director, a video-gen worker, a validator, a compositor, a session manager, a trace recorder. RocketRide lets us declare each one, route the right model to the right job, deploy them as one cohesive runtime, and observe everything they do. Doing this on bare LangChain or a pile of cron jobs is the shallow approach. We use RocketRide as the substrate it was designed to be.
- **Gemini / Veo** is the **counterfactual generator** and the **deep video understander**. Veo is the only model on this planet right now that can take reference frames of an actual match, a structured description of the counterfactual change, and render a visually continuous 8-second clip that looks like it came from the same broadcast. Gemini handles the deep video understanding pass — chunking the buffer into multi-second windows and producing the high-resolution event timeline. Gemini Live carries the conversational interface where the user talks to the system about the match in real time. This is three different Google capabilities used in three different load-bearing roles.

Shallow integrations make a team ineligible. Our integrations are the spine of the system. Pull any of them out and there is no system left.

## Concrete user experience

A user opens What If, pastes a YouTube live link to an ongoing match, and lands on a session view: the live player on the left, a streaming AI commentary panel on the right, a "what-if" composer at the bottom, and a timeline scrubber underneath the player showing every detected event so far (goals, big chances, fouls, subs, set pieces) — each event with a one-line auto-generated caption.

They watch. At minute 24 their team's striker shoots wide. They type "what if he'd squared it to the runner instead." The system:

1. Resolves the moment — "shoots wide at 24:11" → the buffered window [23:55, 24:25].
2. Pulls the actual frames of that window from the on-disk capture buffer.
3. The director agent composes a structured generation prompt: identifies the striker and the runner from the match-state, describes the squared ball, picks the reference frames that fix the camera angle and player appearance, instructs Veo to continue from the moment immediately before the shot.
4. Veo generates an 8-second alternate clip with native audio.
5. The validator agent watches the output and confirms the counterfactual was honoured and visual continuity is intact.
6. The clip slides into a side panel beside the still-playing live match, with a tag showing what real moment it branched from.

The live match has continued the whole time. The user can keep watching, ask another what-if, branch from inside a what-if. At full time they hit "Director's Cut" and get a shareable URL containing a stitched compilation of their what-ifs plus a full provenance trace anyone clicking the link can explore: every frame, every caption, every retrieval, every Veo prompt, every model output, in a navigable tree.

## What this is not

- Not a highlight reel generator over a finished match. The live, temporal, on-the-fly nature is the entire point.
- Not a text-only fantasy commentary. The output is generated video that looks like the broadcast.
- Not a single-model wrapper. It is a multi-agent perception-and-generation system where each model is chosen for a specific role.
- Not "for the demo." Every component is built to keep running for a full 90-minute match with multiple concurrent users in a session.
