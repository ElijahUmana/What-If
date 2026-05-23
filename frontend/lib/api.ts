/* ──────────────────────────────────────────────────────────
 * REST helpers for the FastAPI gateway.
 * ────────────────────────────────────────────────────────── */

import type { Session, Query, TimelineResponse, Clip } from "./types";

const BASE =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
    : (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

/* ── Sessions ── */

export function createSession(sourceUrl: string): Promise<Session> {
  return request<Session>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ source_url: sourceUrl }),
  });
}

/* ── Queries ── */

export function submitQuery(
  sessionId: string,
  text: string,
  anchorPtsMs?: number,
): Promise<Query> {
  return request<Query>(`/api/sessions/${sessionId}/queries`, {
    method: "POST",
    body: JSON.stringify({ text, anchor_pts_ms: anchorPtsMs }),
  });
}

/* ── Timeline ── */

export function fetchTimeline(sessionId: string): Promise<TimelineResponse> {
  return request<TimelineResponse>(`/api/sessions/${sessionId}/timeline`);
}

/* ── Clips ── */

export function fetchClips(sessionId: string): Promise<Clip[]> {
  return request<Clip[]>(`/api/sessions/${sessionId}/clips`);
}
