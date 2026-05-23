/* ──────────────────────────────────────────────────────────
 * WebSocket client for a session.
 *
 * - Auto-reconnects with exponential backoff (max 8 s).
 * - Parses incoming JSON and dispatches to typed handlers.
 * - Returns a disconnect function.
 * ────────────────────────────────────────────────────────── */

import type {
  MatchState,
  CommentaryLine,
  TimelineEvent,
  Query,
  Clip,
} from "./types";

export interface WSHandlers {
  onMatchState: (data: MatchState) => void;
  onCommentary: (data: CommentaryLine) => void;
  onEvent: (data: TimelineEvent) => void;
  onQueryProgress: (data: Partial<Query>) => void;
  onClipReady: (data: Clip) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

const WS_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/^http/, "ws") ??
  "ws://localhost:8000";

export function connectSession(
  sessionId: string,
  handlers: WSHandlers,
): () => void {
  let ws: WebSocket | null = null;
  let attempt = 0;
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  function connect() {
    if (disposed) return;

    ws = new WebSocket(`${WS_BASE}/ws/sessions/${sessionId}`);

    ws.onopen = () => {
      attempt = 0;
      handlers.onOpen?.();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as {
          type: string;
          payload: Record<string, unknown>;
        };

        switch (msg.type) {
          case "match_state.update":
            handlers.onMatchState(msg.payload as unknown as MatchState);
            break;
          case "commentary.line":
            handlers.onCommentary(msg.payload as unknown as CommentaryLine);
            break;
          case "event.created":
            handlers.onEvent(msg.payload as unknown as TimelineEvent);
            break;
          case "query.progress":
            handlers.onQueryProgress(msg.payload as unknown as Partial<Query>);
            break;
          case "clip.ready":
            handlers.onClipReady(msg.payload as unknown as Clip);
            break;
        }
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      handlers.onClose?.();
      if (!disposed) {
        const delay = Math.min(1000 * 2 ** attempt, 8000);
        attempt += 1;
        timer = setTimeout(connect, delay);
      }
    };

    ws.onerror = () => {
      ws?.close();
    };
  }

  connect();

  return () => {
    disposed = true;
    if (timer) clearTimeout(timer);
    ws?.close();
  };
}
