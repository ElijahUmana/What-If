# Infrastructure

A single-region deployment. Everything live in one place to minimise latency between ingest, perception, generation, and frontend.

## Topology

```
                  ┌────────────────────────┐
                  │   Cloudflare DNS + CDN │
                  └───────────┬────────────┘
                              │
            ┌─────────────────┴──────────────────┐
            │                                    │
   ┌────────▼────────┐                  ┌────────▼────────┐
   │  Frontend SSR   │                  │  Object storage │
   │  (Vercel /      │                  │  (GCS bucket    │
   │   Cloud Run)    │                  │   whatif-prod)  │
   └────────┬────────┘                  └────────▲────────┘
            │                                    │
            │ WS + REST                          │ signed URLs
            │                                    │
   ┌────────▼─────────────────────────────────────┐
   │           Session Gateway (FastAPI)           │
   │   - REST API                                  │
   │   - WS fan-out                                │
   │   - Auth (Clerk / NextAuth)                   │
   └────────┬─────────────────────────────────────┘
            │ event bus (NATS JetStream)
   ┌────────▼─────────────────────────────────────┐
   │            RocketRide Runtime                 │
   │  Hosts: IngestAgent · CaptionerAgent ·        │
   │  SummariserAgent · MatchStateAgent ·          │
   │  CommentaryAgent · RetrievalAgent ·           │
   │  DirectorAgent · VideoGenAgent ·              │
   │  ValidatorAgent · CompositorAgent ·           │
   │  SessionAgent · TraceAgent                    │
   └────────┬─────────────────────────────────────┘
            │
            ├──► GMI Cloud (vision + reasoning + embeddings)
            ├──► Google AI Studio / Vertex AI (Gemini + Veo)
            ├──► Postgres + pgvector (managed: Neon / Supabase)
            └──► GCS (session blobs)
```

## Hosting choices

- **Frontend:** Vercel (Next.js native). Free tier sufficient for the session count we expect; pay-as-you-go if it grows.
- **Session Gateway:** Cloud Run (single region, autoscale 1..N, min instances 1 so cold starts don't hit WebSocket reconnects).
- **RocketRide Runtime:** Per RocketRide's deployment model, hosted on the same Cloud Run cluster (or a small GKE Autopilot cluster if RocketRide ships its own controllers).
- **Event bus:** NATS JetStream on a small VM (3-node cluster for HA in prod; single node OK for hackathon). NATS is the lowest-latency option for the pub/sub patterns RocketRide expects.
- **Database:** Neon Postgres (managed, with pgvector enabled). Or Supabase. Either works.
- **Object storage:** GCS in `us-central1` to be close to Vertex AI Veo endpoints.
- **GPU compute for ffmpeg decode:** A small GPU VM (L4 sufficient; T4 also works) on Compute Engine for the IngestAgent (one VM can host many sessions). Or run CPU-only ffmpeg on Cloud Run with a much smaller frame rate — acceptable because we don't need GPU decode unless we go to 4K.

## Secrets

Managed in Google Secret Manager. Loaded into Cloud Run / VMs via service account bindings. Never committed.

Required secrets:
- `GMI_API_KEY` — GMI Cloud inference key.
- `GOOGLE_AI_STUDIO_KEY` — for Gemini API access if going through AI Studio.
- `GOOGLE_CLOUD_PROJECT` + service account JSON — for Vertex AI Veo access.
- `YOUTUBE_OEMBED_KEY` — not strictly required (oEmbed is anonymous).
- `DATABASE_URL` — Postgres connection string.
- `BUCKET_NAME` — GCS bucket.
- `NATS_URL` — message bus.
- `SESSION_SECRET` — JWT signing key.
- `CLOUDFLARE_TOKEN` — for cache purges on directors-cut pages.

## Environments

- `dev` — local: docker-compose with Postgres, NATS, GCS-emulator (`fake-gcs-server`).
- `staging` — full cloud topology, smaller resources, `whatif-staging` bucket.
- `prod` — full cloud topology, `whatif-prod` bucket.

## Provisioning

`infra/` directory contains:
- `terraform/` — GCP project, GCS bucket, Cloud Run services, secret manager bindings, Neon project.
- `docker/` — Dockerfiles for the gateway and each agent kind.
- `compose/` — local dev docker-compose.
- `nats/` — JetStream config.

Bring-up is `terraform apply` + `docker compose up` (dev) or push of CI-built images (cloud).

## Scaling characteristics

- **Sessions are isolated.** Concurrency scales by horizontally scaling agent workers per kind. RocketRide handles routing per session.
- **Ingest is the heaviest per-session worker.** One ffmpeg pipeline per session; pinned to a worker for the session's lifetime. ~1 vCPU + ~0.5 GB RAM per active session at 720p.
- **Captioner is QPS-bound.** Two in-flight per session at 2 fps = 4 requests/s. Capacity is bound by the GMI account QPS limit, not our compute.
- **Summariser is the heaviest LLM cost.** One Gemini call per 30 s per session, but each is a multi-megabyte payload. Plan for ~$0.10–0.50 per match per session (highly dependent on token pricing).
- **Veo is the heaviest single call.** ~$X per 8-second clip (filled in by tech docs).
- **Database load** is trivial; pgvector queries are sub-100 ms at our cardinality.

## Cost guard rails

- Per-session budget alarm. If estimated cost exceeds a configured ceiling, the session is marked degraded: summariser drops to a cheaper model, captioner samples less frequently, Veo is rate-limited to 1 in-flight.
- Per-user free tier with bring-your-own-key option for power users.

## Observability

- All agent logs structured JSON, shipped to Cloud Logging.
- Trace events doubled into Cloud Trace via an exporter for service-level observability (latency p50/p99, error rates).
- Per-agent dashboard in Cloud Monitoring with the operator console replicated locally for the trace explorer audience.

## Security

- All WebSocket sessions authenticated; session IDs are unguessable ULIDs.
- Object storage uses signed URLs with short TTLs (1 hour) for all artifact reads.
- Public director's-cut pages serve static HTML + signed CDN URLs that are rotated on revoke.
- No user input is interpolated into shell commands; ffmpeg is invoked with arg arrays.
- Rate limits on every public endpoint.

## Compliance

- SynthID watermark preserved on Veo output.
- Source live streams are not redistributed; only what-if generations and small reference thumbnails are persisted publicly.
- A "delete my session" endpoint hard-deletes blobs and trace rows.

## DR

- Postgres point-in-time recovery (Neon does this natively).
- GCS bucket versioning enabled on the artifact paths.
- Trace WAL on each agent host allows recovery of in-flight trace rows.

## What we deliberately do not have

- No Kubernetes cluster of our own. Cloud Run + a single small VM for NATS is sufficient.
- No message queue beyond NATS. No Kafka.
- No CDN for video other than what GCS provides via signed URLs. Cloudflare in front for the static landing pages.
- No analytics / tracking pixel. The provenance store *is* the analytics store.
