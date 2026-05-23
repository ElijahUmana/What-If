"""Resolve a YouTube live URL to an HLS manifest URL via yt-dlp."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_YT_DLP = "/opt/anaconda3/bin/yt-dlp"

# Primary command: uses cookies for auth-gated / age-gated streams
_PRIMARY_ARGS = [
    _YT_DLP,
    "--remote-components", "ejs:github",
    "--js-runtimes", "node",
    "--cookies-from-browser", "chrome",
    "-f", "300",
    "-g",
]

# Fallback command: still needs cookies (YouTube blocks without), relaxed format
_FALLBACK_ARGS = [
    _YT_DLP,
    "--remote-components", "ejs:github",
    "--js-runtimes", "node",
    "--cookies-from-browser", "chrome",
    "-f", "bv*[height<=720]",
    "-g",
]


def resolve_manifest(youtube_url: str, timeout: int = 60) -> str:
    """Resolve a YouTube live URL to a direct HLS/DASH manifest URL.

    Tries the primary command first (with cookies + format 300).
    On any failure, retries once with a plain fallback (no cookies,
    best-video <=720p).

    Args:
        youtube_url: Full YouTube watch URL.
        timeout: Subprocess timeout in seconds per attempt.

    Returns:
        The manifest URL (first line of yt-dlp stdout).

    Raises:
        RuntimeError: Both primary and fallback attempts failed.
    """
    last_err: Exception | None = None

    for label, base_args in [("primary", _PRIMARY_ARGS), ("fallback", _FALLBACK_ARGS)]:
        cmd = [*base_args, youtube_url]
        logger.info("resolve_manifest [%s]: %s", label, " ".join(cmd))
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
            manifest_url = result.stdout.strip().splitlines()[0]
            logger.info("resolve_manifest [%s]: got %s", label, manifest_url[:120])
            return manifest_url
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError) as exc:
            last_err = exc
            logger.warning("resolve_manifest [%s] failed: %s", label, exc)

    raise RuntimeError(
        f"Failed to resolve manifest for {youtube_url} after primary + fallback. "
        f"Last error: {last_err}"
    )
