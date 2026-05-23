"""Local filesystem storage that mimics GCS interface."""

import os
from pathlib import Path

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "/tmp/whatif_storage")


def ensure_dir(path: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def store(
    session_id: str, category: str, filename: str, data: bytes
) -> str:
    path = f"{STORAGE_ROOT}/sessions/{session_id}/{category}/{filename}"
    ensure_dir(path)
    with open(path, "wb") as f:
        f.write(data)
    return path


def fetch(uri: str) -> bytes:
    with open(uri, "rb") as f:
        return f.read()


def list_files(session_id: str, category: str) -> list[str]:
    d = f"{STORAGE_ROOT}/sessions/{session_id}/{category}"
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d))
