/* ──────────────────────────────────────────────────────────
 * YouTube URL helpers.
 * ────────────────────────────────────────────────────────── */

/**
 * Extract the YouTube video ID from various URL formats:
 *  - https://www.youtube.com/watch?v=VIDEO_ID
 *  - https://youtu.be/VIDEO_ID
 *  - https://www.youtube.com/live/VIDEO_ID
 *  - https://www.youtube.com/embed/VIDEO_ID
 *
 * Returns null if no ID can be extracted.
 */
export function extractYouTubeId(url: string): string | null {
  try {
    const u = new URL(url);

    // youtu.be/ID
    if (u.hostname === "youtu.be") {
      return u.pathname.slice(1).split("/")[0] || null;
    }

    // youtube.com/watch?v=ID
    const v = u.searchParams.get("v");
    if (v) return v;

    // youtube.com/live/ID or youtube.com/embed/ID
    const match = u.pathname.match(/\/(live|embed)\/([^/?]+)/);
    if (match) return match[2];

    return null;
  } catch {
    return null;
  }
}

/**
 * Build an embeddable YouTube URL for an iframe.
 * Falls back to the raw URL if no ID can be extracted.
 */
export function toEmbedUrl(sourceUrl: string): string {
  const id = extractYouTubeId(sourceUrl);
  if (id) {
    return `https://www.youtube.com/embed/${id}?autoplay=1&modestbranding=1&rel=0`;
  }
  return sourceUrl;
}
