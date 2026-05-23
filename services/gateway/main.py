import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import sessions, queries, artifacts, traces
from .ws import router as ws_router

app = FastAPI(title="What If Gateway")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(sessions.router, prefix="/api")
app.include_router(queries.router, prefix="/api")
app.include_router(artifacts.router, prefix="/api")
app.include_router(traces.router, prefix="/api")
app.include_router(ws_router)

@app.get("/health")
def health():
    return {"status": "ok"}
