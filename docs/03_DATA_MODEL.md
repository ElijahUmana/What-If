# Data Model

Every artifact in the system has an ID, a parent, a timestamp, and a content hash. Provenance is not an afterthought — it is encoded in the shape of the data.

## Identifiers

All IDs are 26-char ULIDs (sortable by creation time, URL-safe).
Trace events use `tr_…`, agents `ag_…`, sessions `ss_…`, chunks `ch_…`, frames `fr_…`, captions `cp_…`, summaries `sm_…`, events `ev_…`, queries `qr_…`, prompts `pr_…`, generations `gn_…`, clips `cl_…`, artifacts `ar_…`.

## Storage layout

- **Postgres** — all structured rows, plus pgvector embeddings.
- **Object storage (GCS bucket)** — all binary artifacts: video chunks, decoded frames, generated clips, composed director's-cut MP4s.
- **Redis** — hot caches: latest frame per session, current match state, in-flight job status.

## Tables (Postgres)

### session
| col | type | notes |
|---|---|---|
| id | text PK | `ss_…` |
| created_at | timestamptz | |
| owner_user_id | text FK | |
| source_url | text | YouTube live URL |
| source_kind | text | `youtube_live` for now, extensible |
| ingest_started_at | timestamptz | |
| ingest_status | text | `starting`, `live`, `paused`, `closed`, `errored` |
| last_chunk_id | text FK | latest written chunk |
| match_meta | jsonb | teams, kickoff, competition, detected by setup agent |
| visibility | text | `private`, `unlisted`, `public` |

### chunk
Each chunk is a 2-second HLS segment as written by the ingest worker.
| col | type | notes |
|---|---|---|
| id | text PK | |
| session_id | text FK | |
| sequence | int | monotonic per session |
| start_pts_ms | bigint | source-stream presentation timestamp |
| end_pts_ms | bigint | |
| duration_ms | int | normally 2000 |
| storage_uri | text | `gs://…/sessions/ss_…/chunks/00001234.ts` |
| storage_bytes | bigint | |
| created_at | timestamptz | |
| codec | text | `h264`, `h265` |
| resolution | text | `1280x720` |
| content_sha256 | text | |

### frame
Reference frames are pre-decoded at 2 fps (configurable per session). The full resolution is kept; thumbnails are derived on demand.
| col | type | notes |
|---|---|---|
| id | text PK | |
| session_id | text FK | |
| chunk_id | text FK | which chunk it was decoded from |
| pts_ms | bigint | exact frame timestamp in source |
| sampled_at_ms | bigint | wall-clock when extracted |
| storage_uri | text | `gs://…/sessions/ss_…/frames/0000123456.jpg` |
| width | int | |
| height | int | |
| sha256 | text | dedup key |

### caption
Per-frame fast caption, written by `FrameCaptionerAgent` (GMI VL).
| col | type | notes |
|---|---|---|
| id | text PK | |
| session_id | text FK | |
| frame_id | text FK | |
| pts_ms | bigint | denormalised |
| text | text | one-line factual description |
| entities | jsonb | detected players/jersey numbers/locations |
| model_id | text | which GMI model produced it |
| latency_ms | int | |
| trace_id | text FK | |

### summary
Per-buffer multi-frame summary, written by `SummariserAgent`.
| col | type | notes |
|---|---|---|
| id | text PK | |
| session_id | text FK | |
| start_pts_ms | bigint | window start |
| end_pts_ms | bigint | window end (≈30 s window) |
| frame_ids | text[] | the frames fed to the summariser |
| caption_ids | text[] | the captions in the window |
| narrative | text | a paragraph of what happened |
| structured | jsonb | `{phase, possession, dangerous_situation, key_action, players}` |
| model_id | text | |
| trace_id | text FK | |

### event
A detected discrete game event (goal, shot, foul, sub, set piece, var review). Extracted by the summariser when its `structured.key_action` warrants it, then enriched by `MatchStateAgent`.
| col | type | notes |
|---|---|---|
| id | text PK | |
| session_id | text FK | |
| type | text | `goal`, `shot_on_target`, `shot_off_target`, `foul`, `card`, `sub`, `corner`, `freekick`, `penalty`, `var`, `kickoff`, `halftime`, `fulltime`, `chance`, `save`, `tackle`, `offside` |
| start_pts_ms | bigint | |
| end_pts_ms | bigint | |
| anchor_frame_id | text FK | the single most representative frame |
| actors | jsonb | `[{role: "shooter", player: "..."}, …]` |
| description | text | concise human-readable |
| confidence | float | 0–1 |
| summary_id | text FK | the summary that produced this |
| trace_id | text FK | |

### match_state
Versioned snapshots of the running structured match model.
| col | type | notes |
|---|---|---|
| id | text PK | |
| session_id | text FK | |
| as_of_pts_ms | bigint | |
| score | jsonb | `{home: 1, away: 0}` |
| period | text | `1st_half`, `halftime`, `2nd_half`, `et1`, `et2`, `pens`, `ft` |
| period_clock_ms | bigint | |
| home | jsonb | `{name, kit_color, formation, on_pitch: [...players...]}` |
| away | jsonb | same shape |
| momentum | jsonb | rolling xG-style scalars |
| trace_id | text FK | |

### caption_embedding / summary_embedding / event_embedding
pgvector tables. Same shape:
| col | type | notes |
|---|---|---|
| id | text PK | |
| owner_id | text FK | caption/summary/event |
| embedding | vector(1024) | |
| model_id | text | which embedding model |

### query
Each "what if" issued by a user is a row.
| col | type | notes |
|---|---|---|
| id | text PK | |
| session_id | text FK | |
| user_id | text | who asked |
| text | text | raw user prompt |
| parsed | jsonb | `{anchor_pts_ms, change_type, entities_referenced, intent_clarity}` after parsing |
| status | text | `received`, `resolved`, `directing`, `generating`, `validating`, `ready`, `rejected`, `failed` |
| resolved_anchor_pts_ms | bigint | the final time the system locked onto |
| resolved_window_start_ms | bigint | |
| resolved_window_end_ms | bigint | |
| parent_clip_id | text FK | non-null if this branches from a prior what-if |
| created_at | timestamptz | |
| trace_id | text FK | |

### prompt
Each prompt sent to a generation model is a row, so we can replay any generation.
| col | type | notes |
|---|---|---|
| id | text PK | |
| query_id | text FK | |
| kind | text | `veo_t2v`, `veo_i2v`, `veo_ref_conditioned`, `validator_judge` |
| body | jsonb | full structured prompt including reference frame URIs |
| model_id | text | e.g. `veo-3.0-generate-001` |
| created_at | timestamptz | |

### generation
| col | type | notes |
|---|---|---|
| id | text PK | |
| prompt_id | text FK | |
| status | text | `queued`, `running`, `succeeded`, `failed` |
| started_at | timestamptz | |
| finished_at | timestamptz | |
| latency_ms | int | |
| storage_uri | text | `gs://…/sessions/ss_…/clips/cl_….mp4` |
| metadata | jsonb | duration, resolution, fps, has_audio |
| validator_verdict | text | `ok`, `regenerate`, `reject` |
| validator_reasons | jsonb | structured list of issues |

### clip
A finished, validated what-if clip ready to play.
| col | type | notes |
|---|---|---|
| id | text PK | |
| query_id | text FK | |
| generation_id | text FK | |
| storage_uri | text | |
| duration_ms | int | |
| labels | jsonb | `{branched_from_event_id, branched_from_pts_ms, change_summary}` |

### artifact
The shareable end-of-session product.
| col | type | notes |
|---|---|---|
| id | text PK | |
| session_id | text FK | |
| kind | text | `directors_cut`, `single_clip_share`, `provenance_export` |
| storage_uri | text | |
| short_code | text | URL-safe slug for sharing |
| created_at | timestamptz | |
| revoked_at | timestamptz | nullable |

### trace_event
The provenance store (see `10_PROVENANCE.md` for full spec).
| col | type | notes |
|---|---|---|
| id | text PK | `tr_…` |
| session_id | text FK | |
| agent | text | which agent emitted it |
| kind | text | `model_call`, `tool_call`, `state_write`, `decision`, `error` |
| parent_id | text FK | tree edge |
| started_at | timestamptz | |
| ended_at | timestamptz | |
| input_ref | jsonb | content-addressed input pointers |
| output_ref | jsonb | content-addressed output pointers |
| model_id | text | nullable |
| latency_ms | int | nullable |
| status | text | `ok`, `error`, `partial` |
| payload | jsonb | small structured detail |

## Object-store layout

```
gs://whatif-{env}/sessions/{session_id}/
   chunks/        2-second .ts segments named by sequence
   frames/        decoded reference jpegs named by pts
   keyframes/     full-res frames preserved for Veo conditioning
   clips/         generated what-if mp4s
   composed/      director's-cut mp4s
   audio/         optional commentary audio renders
   exports/       provenance bundles
```

Every file's path encodes the session and the temporal anchor. The session is portable: copy the folder and the Postgres rows for that session and you have everything needed to replay or export.

## Cardinality and budgets

For a 90-minute match at 2 fps reference frames:
- ~10,800 reference frames per session
- ~10,800 captions per session
- ~180 summary buffers (one per 30 s)
- ~30–60 detected discrete events (typical match)
- 2,700 video chunks at 2 s each (~2–4 GB of source video at 720p)

A typical interactive session issues 5–20 what-ifs. Each what-if produces one query row, one prompt row, one generation row, one clip row, and roughly 20–60 trace_event rows.

This is a small enough working set that everything except the raw video can live comfortably in a single Postgres instance.
