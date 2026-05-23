"""Resolve a YouTube URL (live OR recorded) to a direct stream URL via yt-dlp."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_YT_DLP = "/opt/anaconda3/bin/yt-dlp"

_BASE_ARGS = [
    _YT_DLP,
    "--remote-components", "ejs:github",
    "--js-runtimes", "node",
    "--cookies-from-browser", "chrome",
]


def resolve_manifest(youtube_url: str, timeout: int = 90) -> str:
    """Resolve a YouTube URL to a direct stream/download URL.

    Works for both live streams AND regular (recorded/ended) videos.
    Tries multiple format selections in order of preference.
    """
    format_attempts = [
        ("720p-live", "300"),
        ("720p-best", "bv*[height<=720]+ba/b[height<=720]"),
        ("any-720p", "bv*[height<=720]"),
        ("any-best", "bv*+ba/b"),
    ]

    last_err: Exception | None = None

    for label, fmt in format_attempts:
        cmd = [*_BASE_ARGS, "-f", fmt, "-g", youtube_url]
        logger.info("resolve [%s]: %s", label, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=True,
            )
            url = result.stdout.strip().splitlines()[0]
            logger.info("resolve [%s]: got URL len=%d", label, len(url))
            return url
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError) as exc:
            last_err = exc
            logger.warning("resolve [%s] failed: %s", label, exc)

    raise RuntimeError(f"All format attempts failed for {youtube_url}. Last: {last_err}")
