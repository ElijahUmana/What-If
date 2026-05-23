/* ──────────────────────────────────────────────────────────
 * Shared type definitions for the What If frontend.
 * Every component imports from here — no inline `any`.
 * ────────────────────────────────────────────────────────── */

/* ── Session ── */

export interface Session {
  session_id: string;
  source_url: string;
  ingest_status: "pending" | "ingesting" | "ready" | "error";
}

/* ── Match state ── */

export interface MatchState {
  home_team: string;
  away_team: string;
  home_score: number;
  away_score: number;
  period: string;
  clock: string;
  home_logo_url?: string;
  away_logo_url?: string;
}

/* ── Commentary ── */

export interface CommentaryLine {
  id: string;
  text: string;
  pts_ms?: number;
  timestamp: string;
  type?: "standard" | "highlight" | "analysis";
}

/* ── Timeline event ── */

export type EventType =
  | "goal"
  | "shot"
  | "foul"
  | "card"
  | "substitution"
  | "corner"
  | "offside"
  | "kickoff"
  | "halftime"
  | "fulltime"
  | "other";

export interface TimelineEvent {
  id: string;
  type: EventType;
  description: string;
  pts_ms: number;
  match_clock: string;
  team?: string;
  player?: string;
}

/* ── Query (what-if) ── */

export type QueryStatus =
  | "submitted"
  | "resolving"
  | "retrieving"
  | "composing"
  | "generating"
  | "validating"
  | "compositing"
  | "complete"
  | "failed";

export interface Query {
  id: string;
  text: string;
  anchor_pts_ms?: number;
  status: QueryStatus;
  progress_pct?: number;
  stage_label?: string;
  clip_id?: string;
  error?: string;
  created_at: string;
}

/* ── Clip ── */

export interface Clip {
  id: string;
  query_id: string;
  prompt_text?: string;
  prompt?: string;
  video_url?: string;
  storage_uri?: string;
  thumbnail_url?: string;
  duration_ms: number;
  created_at?: string;
}

/* ── WebSocket messages ── */

export type WSIncomingType =
  | "match_state.update"
  | "commentary.line"
  | "event.created"
  | "query.progress"
  | "clip.ready";

export interface WSIncomingMessage {
  type: WSIncomingType;
  payload: Record<string, unknown>;
}

export interface WSOutgoingQuery {
  type: "query.submit";
  payload: {
    text: string;
    anchor_pts_ms?: number;
  };
}

/* ── Timeline API response ── */

export interface TimelineResponse {
  events: TimelineEvent[];
  summaries: Array<{ period: string; text: string }>;
  match_state: MatchState;
}
