# Repository Layout

A pnpm + uv monorepo. Three top-level language stacks live together: TypeScript for the frontend, Python for the gateway and the agents, and a small amount of shell/Terraform for infra. All packages share lockfiles at the root.

```
What-If/
├── README.md                       # overview + quickstart
├── docs/                           # this directory: the master plan
│   ├── 01_VISION.md
│   ├── 02_ARCHITECTURE.md
│   ├── 03_DATA_MODEL.md
│   ├── 04_PIPELINE.md
│   ├── 05_AGENTS.md
│   ├── 06_TECH_GMI_CLOUD.md
│   ├── 07_TECH_ROCKETRIDE.md
│   ├── 08_TECH_GEMINI_VEO.md
│   ├── 09_USER_FLOWS.md
│   ├── 10_PROVENANCE.md
│   ├── 11_FRONTEND.md
│   ├── 12_SHARING.md
│   ├── 13_INFRA.md
│   ├── 14_REPO_LAYOUT.md
│   └── 15_BUILD_TEAM_TASKS.md
├── package.json                    # pnpm workspaces root
├── pnpm-workspace.yaml
├── pyproject.toml                  # uv-managed Python deps root
├── uv.lock
├── .env.example
│
├── frontend/                       # Next.js 15 app
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── public/
│   ├── tailwind.config.ts
│   └── package.json
│
├── services/
│   ├── gateway/                    # FastAPI + WebSocket
│   │   ├── whatif_gateway/
│   │   │   ├── main.py
│   │   │   ├── ws.py
│   │   │   ├── auth.py
│   │   │   ├── routes/
│   │   │   ├── trace_api.py
│   │   │   └── artifacts_api.py
│   │   └── pyproject.toml
│   └── index/                      # write-through index service (thin)
│       ├── whatif_index/
│       │   ├── postgres.py
│       │   ├── pgvector.py
│       │   └── schemas/
│       └── pyproject.toml
│
├── agents/
│   ├── _lib/                       # shared helpers
│   │   ├── trace.py                # trace span wrapper
│   │   ├── bus.py                  # RocketRide pubsub helpers
│   │   ├── gmi.py                  # GMI Cloud client
│   │   ├── gemini.py               # Google AI / Vertex client
│   │   ├── veo.py                  # Veo client wrapper
│   │   ├── storage.py              # GCS client + signed URLs
│   │   └── ids.py                  # ULID helpers
│   ├── ingest/
│   │   ├── agent.py
│   │   ├── ffmpeg_pipeline.py
│   │   ├── youtube_resolver.py
│   │   └── rocketride.agent.yaml
│   ├── captioner/
│   │   ├── agent.py
│   │   ├── prompt.md
│   │   └── rocketride.agent.yaml
│   ├── summariser/
│   │   ├── agent.py
│   │   ├── prompt.md
│   │   └── rocketride.agent.yaml
│   ├── state/
│   ├── commentary/
│   ├── retrieval/
│   ├── director/
│   ├── videogen/
│   ├── validator/
│   ├── compositor/
│   │   ├── ffmpeg_compose.py
│   │   └── branch_card_template.svg
│   ├── session/
│   ├── trace/
│   └── setup/                      # match-metadata one-shot agent
│
├── prompts/                        # all prompt bodies (versioned)
│   ├── captioner.system.md
│   ├── captioner.user_template.md
│   ├── summariser.system.md
│   ├── retrieval.rerank.md
│   ├── director.system.md
│   ├── director.veo_schema.md
│   ├── validator.fidelity.md
│   ├── validator.continuity.md
│   ├── commentary.persona.md
│   └── setup.match_meta.md
│
├── schemas/                        # shared schemas (Python + TS via codegen)
│   ├── trace.openapi.yaml
│   ├── ws.openapi.yaml
│   ├── domain/
│   │   ├── session.py
│   │   ├── frame.py
│   │   ├── caption.py
│   │   ├── summary.py
│   │   ├── event.py
│   │   ├── match_state.py
│   │   ├── query.py
│   │   ├── prompt.py
│   │   ├── generation.py
│   │   ├── clip.py
│   │   └── artifact.py
│   └── ts/                         # generated TS clients
│
├── infra/
│   ├── terraform/
│   │   ├── gcp/
│   │   ├── neon/
│   │   └── cloudflare/
│   ├── docker/
│   │   ├── gateway.Dockerfile
│   │   ├── agent.Dockerfile
│   │   ├── ingest.Dockerfile          # GPU-enabled ffmpeg base
│   │   └── nats.Dockerfile
│   ├── compose/
│   │   ├── docker-compose.dev.yaml
│   │   └── docker-compose.prod.yaml
│   ├── migrations/
│   │   ├── 0001_init.sql
│   │   ├── 0002_pgvector.sql
│   │   └── 0003_trace.sql
│   └── nats/
│       └── jetstream.conf
│
├── scripts/
│   ├── dev/
│   │   ├── boot_local.sh
│   │   ├── seed_match.sh
│   │   └── tail_session.sh
│   ├── deploy/
│   │   ├── build_images.sh
│   │   └── push_and_release.sh
│   └── ops/
│       ├── replay_trace.py
│       └── export_session.py
│
├── tests/
│   ├── agents/
│   ├── gateway/
│   ├── frontend/
│   └── e2e/
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── release.yml
│   └── CODEOWNERS
│
└── .vscode/
    └── settings.json               # RocketRide extension picks up agents/
```

## Conventions

- **Each agent is its own deployable.** A `rocketride.agent.yaml` declares the agent. The Python implementation lives next to it.
- **Prompts are files, not strings.** Every prompt body is in `prompts/`. Tests assert prompts have the placeholders they need.
- **Schemas are the source of truth.** OpenAPI for cross-language contracts (WS protocol, trace API), Pydantic for in-Python domain models, codegen produces TS clients.
- **No untested code path on the hot perception loop.** Captioner, summariser, retrieval, director, validator, compositor each have unit tests and a recorded-fixture integration test.

## Boot order (local)

```
1. docker compose up postgres nats fake-gcs       # infra
2. uv run alembic upgrade head                    # migrations
3. uv run python -m services.gateway              # gateway
4. uv run rocketride dev                          # agent runtime (live-reload)
5. pnpm --filter ./frontend dev                   # frontend
```

A single `make dev` orchestrates all five.

## Build, lint, test

- Python: `uv run ruff check`, `uv run pytest`, `uv run mypy`.
- TS: `pnpm lint`, `pnpm test`, `pnpm typecheck`.
- All gated in CI before any deploy.
