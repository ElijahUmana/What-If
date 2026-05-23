# YouTube Live Ingest — Technical Implementation

This is the specification for the IngestAgent's actual implementation. The agent boundary, contracts, and trace footprint are in `05_AGENTS.md`; the data shape lands in `03_DATA_MODEL.md`. This document is the precise mechanics.

## Stack

| Layer | Choice | Why |
|---|---|---|
| YouTube URL resolution | `yt-dlp` ≥ 2026.03.17 | Only tool that handles YouTube's current PO-token + n-parameter JS challenges. |
| JavaScript runtime (required by yt-dlp) | `deno` (default) | Required since yt-dlp v2025.11.12. PhantomJS deprecated. |
| Stream capture | `ffmpeg` ≥ 6.x with libx264 + nvdec | Tee muxer + segment muxer + reconnect flags + nvdec for GPU decode. |
| Process wrapper | Python `subprocess` | We do NOT use the abandoned `ffmpeg-python` package. |
| Frame decoding | `PyAV` (for in-process reads) + `cv2.imencode` (JPEG-on-encode) | Direct libav bindings, low overhead. |
| Ring buffer | `collections.deque(maxlen=N)` | Thread-safe append/pop, fixed memory. |
| Time index | `bisect` (stdlib) | O(log n) on PTS lookups. |
| File watcher | `watchdog` ≥ 6 | inotify/FSEvents/kqueue per platform. |
| Per-chunk fan-out | Redis Streams | Replay-capable append-only log; late joiners can catch up. |
| Hosting | RunPod RTX 4090 GPU pod ($0.39/hr) for continuous capture; Modal functions for AI analysis bursts. | Fly.io GPU is being deprecated (gone after 2026-08-01) — RunPod is the right choice. |

## Master ffmpeg command

A **single** ffmpeg process per session, using the `tee` pseudo-muxer to fork the stream into three concurrent consumers (segments, frames, full archive), encoded once.

```bash
STREAM_URL=$(yt-dlp -g -f "bv*[height<=720]+ba/b[height<=720]" --hls-use-mpegts "$YOUTUBE_URL")

ffmpeg \
  -reconnect 1 -reconnect_streamed 1 \
  -reconnect_delay_max 30 \
  -reconnect_on_network_error 1 \
  -reconnect_on_http_error 5xx \
  -hwaccel cuda -hwaccel_output_format cuda -c:v h264_cuvid \
  -i "$STREAM_URL" \
  -map 0:v -map 0:a \
  -c:v copy -c:a copy \
  -f tee \
    "[f=segment:segment_time=2:segment_format=mpegts:reset_timestamps=1:segment_list=chunks/index.csv:segment_list_type=csv:strftime=1]chunks/chunk_%Y%m%d_%H%M%S.ts| \
     [f=image2pipe:vf=fps=2,scale=1280:720:hwdownload,format=nv12:q:v=4]frames/%010d.jpg| \
     [f=mpegts]archive/full_stream.ts"
```

What this command does, output by output:

1. **`chunks/chunk_*.ts`** — 2-second MPEG-TS segments with wall-clock filename. `index.csv` is the running manifest: `chunk_file,start_time,end_time`.
2. **`frames/%010d.jpg`** — reference frames at 2 fps, 720p, JPEG quality 4 (default ffmpeg scale). Filename is a monotonic integer for trivial sequencing.
3. **`archive/full_stream.ts`** — continuous concatenated archive for whole-match retrieval. Used by the Provenance Export bundler.

`-hls-use-mpegts` on yt-dlp's side forces MPEG-TS into the manifest, which is resilient to interrupt — a crashed ffmpeg leaves valid `.ts` files on disk.

Note: GPU decode (`h264_cuvid`) is conditional on the host having an NVIDIA GPU. On RunPod RTX 4090 it works; on CPU-only Cloud Run we drop the `-hwaccel`/`-c:v h264_cuvid` flags and accept ~30% more CPU.

## Resilience: URL refresh + reconnect

yt-dlp-extracted manifest URLs expire after some hours. ffmpeg's reconnect flags handle short network glitches but not URL expiry. The supervisor:

```python
import subprocess, time, signal, os

class IngestSupervisor:
    def __init__(self, youtube_url: str, work_dir: str) -> None:
        self.url = youtube_url
        self.work_dir = work_dir
        self.proc: subprocess.Popen | None = None

    def resolve_stream_url(self) -> str:
        out = subprocess.run(
            ["yt-dlp", "-g", "-f", "bv*[height<=720]+ba/b[height<=720]", "--hls-use-mpegts", self.url],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return out.stdout.strip().splitlines()[0]

    def start_ffmpeg(self, stream_url: str) -> subprocess.Popen:
        cmd = build_ffmpeg_cmd(stream_url, self.work_dir)  # see above
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def run_forever(self) -> None:
        backoff = 2
        while True:
            try:
                stream_url = self.resolve_stream_url()
                self.proc = self.start_ffmpeg(stream_url)
                self.proc.wait()
                rc = self.proc.returncode
                # ffmpeg returns 0 on graceful end (stream over). non-zero = crash/disconnect.
                if rc == 0:
                    return  # stream actually ended
                # crash — back off and re-resolve
            except Exception:
                pass
            time.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 60)
```

The supervisor runs as the IngestAgent's main task. On every reconnect, a new chunk sequence resumes from `chunks/index.csv`'s next number.

## Chunk indexer (Postgres write-through)

`watchdog` notices each new `.ts` close-write:

```python
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
import subprocess, json

class ChunkIndexer(FileSystemEventHandler):
    def __init__(self, session_id: str, db, storage, bus) -> None:
        self.session_id = session_id
        self.db = db
        self.storage = storage
        self.bus = bus

    def on_closed(self, event):
        if event.src_path.endswith('.ts'):
            self._index(event.src_path)

    def _index(self, path: str) -> None:
        info = self._probe(path)
        uri = self.storage.upload(path, f"sessions/{self.session_id}/chunks/{os.path.basename(path)}")
        chunk_id = self.db.insert_chunk(
            session_id=self.session_id,
            sequence=self._next_seq(),
            start_pts_ms=int(info["start_time"] * 1000),
            end_pts_ms=int((info["start_time"] + info["duration"]) * 1000),
            duration_ms=int(info["duration"] * 1000),
            storage_uri=uri,
            storage_bytes=os.path.getsize(path),
            codec=info["codec"],
            resolution=info["resolution"],
            content_sha256=sha256_file(path),
        )
        self.bus.publish("chunk.created", {
            "session_id": self.session_id,
            "chunk_id": chunk_id,
            "start_pts_ms": int(info["start_time"] * 1000),
        })

    def _probe(self, path: str) -> dict:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(r.stdout)
        v = next(s for s in data["streams"] if s["codec_type"] == "video")
        return {
            "start_time": float(data["format"].get("start_time", 0.0)),
            "duration": float(data["format"].get("duration", 2.0)),
            "codec": v["codec_name"],
            "resolution": f"{v['width']}x{v['height']}",
        }
```

The same pattern applies to `frames/` for the FrameCaptionerAgent's input.

## Frame ring buffer (in-process)

Most sessions need fast access to the last 5 minutes of frames without round-tripping object storage. A bounded JPEG ring buffer covers that:

```python
from collections import deque
from threading import Lock
import time

class FrameRing:
    def __init__(self, max_frames: int = 600) -> None:  # 5 min @ 2 fps
        self.buf: deque[dict] = deque(maxlen=max_frames)
        self.lock = Lock()

    def append(self, pts_ms: int, jpeg_bytes: bytes) -> None:
        with self.lock:
            self.buf.append({"pts_ms": pts_ms, "wall_ts": time.time(), "jpeg": jpeg_bytes})

    def window(self, start_pts_ms: int, end_pts_ms: int) -> list[dict]:
        with self.lock:
            return [f for f in self.buf if start_pts_ms <= f["pts_ms"] <= end_pts_ms]

    def last_n_seconds(self, seconds: float) -> list[dict]:
        with self.lock:
            if not self.buf:
                return []
            cutoff = self.buf[-1]["pts_ms"] - int(seconds * 1000)
            return [f for f in self.buf if f["pts_ms"] >= cutoff]
```

Memory budget at JPEG quality 85: ~60–100 KB per 720p frame. Full 90-minute match at 2 fps ≈ 700 MB if we kept everything; we keep last 5 min hot in memory (≈ 90 MB) and rely on object storage for older frames.

## Replay clip extraction

A clip for Veo conditioning is built from the chunk archive with no re-encode:

```python
def extract_clip(session_id: str, start_pts_ms: int, duration_ms: int, out_path: str) -> str:
    chunks = db.chunks_overlapping(session_id, start_pts_ms, start_pts_ms + duration_ms)
    if not chunks:
        raise ValueError("no chunks in range")
    # Localize chunks from object storage (cached on disk)
    local_paths = [storage.fetch(c["storage_uri"]) for c in chunks]
    concat = "|".join(local_paths)
    offset_in_first = (start_pts_ms - chunks[0]["start_pts_ms"]) / 1000.0
    duration_s = duration_ms / 1000.0
    subprocess.run([
        "ffmpeg", "-y",
        "-i", f"concat:{concat}",
        "-ss", f"{offset_in_first:.3f}",
        "-t", f"{duration_s:.3f}",
        "-c", "copy", "-bsf:a", "aac_adtstoasc",
        out_path,
    ], check=True)
    return out_path
```

Sub-second extraction on local SSD. Pure stream copy — no quality loss.

## Frame format for Veo

Veo 3.1 accepts PNG or JPEG up to 20 MB per reference image. We send **PNG** (lossless) to avoid double-compressing JPEG → JPEG. The reference-frame loader:

```python
import cv2, numpy as np
from google.genai import types

def reference_image_from_frame_jpeg(jpeg_bytes: bytes) -> types.Image:
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    # Ensure 16:9 — let downstream resize 1280x720 as needed
    ok, png = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("png encode failed")
    return types.Image(image_bytes=png.tobytes(), mime_type="image/png")
```

## Synchronisation with the frontend player

YouTube broadcasts at normal latency (15–30 s end-to-end). Our pipeline adds 2–5 s. The frontend embeds the YouTube IFrame Player, and the YouTube Player API exposes `player.getCurrentTime()` — seconds since the start of the broadcast. Our capture indexes PTS from the same origin, so:

```python
class TimeAligner:
    def __init__(self) -> None:
        self.capture_start_pts_ms: int | None = None  # PTS of first frame we captured

    def youtube_seconds_to_pts_ms(self, yt_seconds: float) -> int:
        if self.capture_start_pts_ms is None:
            return int(yt_seconds * 1000)
        return self.capture_start_pts_ms + int(yt_seconds * 1000)
```

When the user right-clicks the live player to anchor a what-if "at this moment," the frontend sends `{youtube_time, type: "anchor"}`; the gateway translates to a PTS and the rest of the pipeline uses that.

## Ad-break detection

YouTube live streams have mid-roll ads. The HLS manifest may include `#EXT-X-DISCONTINUITY` and PTS will jump. We watch for:

1. PTS gaps > 5 s between consecutive chunks (much larger than our 2 s segment cadence).
2. A `blackdetect` filter pass on each chunk:
   ```bash
   ffmpeg -i chunk.ts -vf "blackdetect=d=0.5:pix_th=0.10" -f null - 2>&1 | grep blackdetect
   ```
3. Cosine drift in caption embeddings (the captioner sees ads as a topic shift).

Chunks flagged as ad-breaks are stored with `event.type = "ad_break"` so retrieval and summarisation can skip them.

## Concurrency and scaling

- **Per session**: one IngestSupervisor + one ffmpeg + one watchdog observer per chunk dir + one per frames dir. ~1 vCPU, 800 MB RAM (with the ring buffer), one GPU decode lane.
- **Multiple users on the same source**: future scale-out — one supervisor per source, fan-out via Redis Streams (`stream:{session_id}:chunk_created`). For now, each session is its own source.
- **Backpressure**: if downstream agents fall behind, the chunk indexer keeps working (chunks land safely); the captioner drops oldest unsampled frames (Pipeline A in `04_PIPELINE.md`).

## DR

- Chunks are uploaded to GCS as soon as ffprobe completes; survives node failure.
- `archive/full_stream.ts` is the canonical at-rest copy — even if individual chunk indexing fails, the full stream remains.
- On restart, the supervisor reads the latest sequence from Postgres and resumes from the next chunk.

## What we deliberately do NOT do

- We do not re-encode the stream. Stream-copy only. Quality stays broadcast-grade, CPU stays low.
- We do not store decoded frames on disk in raw form. JPEG q85 is good enough as a reference; full-quality keyframes are pulled from the source `.ts` on demand via `extract_clip`.
- We do not use WebRTC re-streaming. The user's player is YouTube's iframe. We don't act as an intermediate broadcaster.
- We do not use `ffmpeg-python` (abandoned). Subprocess only.
- We do not use Pub/Sub for fan-out where late joiners would miss events. Redis Streams.
