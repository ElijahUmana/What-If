/* ──────────────────────────────────────────────────────────
 * Global Zustand store for session state.
 * ────────────────────────────────────────────────────────── */

import { create } from "zustand";
import type {
  MatchState,
  CommentaryLine,
  TimelineEvent,
  Query,
  Clip,
} from "./types";

interface SessionState {
  /* ── Data ── */
  sessionId: string | null;
  sourceUrl: string | null;
  matchState: MatchState | null;
  commentary: CommentaryLine[];
  events: TimelineEvent[];
  queries: Query[];
  clips: Clip[];
  ingestStatus: string;
  wsConnected: boolean;

  /* ── Actions ── */
  setSession: (id: string, url: string) => void;
  setIngestStatus: (status: string) => void;
  setWsConnected: (connected: boolean) => void;
  updateMatchState: (state: MatchState) => void;
  addCommentary: (line: CommentaryLine) => void;
  addEvent: (event: TimelineEvent) => void;
  setEvents: (events: TimelineEvent[]) => void;
  addQuery: (query: Query) => void;
  updateQuery: (queryId: string, updates: Partial<Query>) => void;
  addClip: (clip: Clip) => void;
  setClips: (clips: Clip[]) => void;
  reset: () => void;
}

const INITIAL: Pick<
  SessionState,
  | "sessionId"
  | "sourceUrl"
  | "matchState"
  | "commentary"
  | "events"
  | "queries"
  | "clips"
  | "ingestStatus"
  | "wsConnected"
> = {
  sessionId: null,
  sourceUrl: null,
  matchState: null,
  commentary: [],
  events: [],
  queries: [],
  clips: [],
  ingestStatus: "pending",
  wsConnected: false,
};

export const useSessionStore = create<SessionState>((set) => ({
  ...INITIAL,

  setSession: (id, url) => set({ sessionId: id, sourceUrl: url }),

  setIngestStatus: (status) => set({ ingestStatus: status }),

  setWsConnected: (connected) => set({ wsConnected: connected }),

  updateMatchState: (state) => set({ matchState: state }),

  addCommentary: (line) =>
    set((s) => ({
      commentary: [...s.commentary, line],
    })),

  addEvent: (event) =>
    set((s) => {
      if (s.events.some((e) => e.id === event.id)) return s;
      return {
        events: [...s.events, event].sort((a, b) => a.pts_ms - b.pts_ms),
      };
    }),

  setEvents: (events) =>
    set({ events: [...events].sort((a, b) => a.pts_ms - b.pts_ms) }),

  addQuery: (query) =>
    set((s) => ({
      queries: [...s.queries, query],
    })),

  updateQuery: (queryId, updates) =>
    set((s) => ({
      queries: s.queries.map((q) =>
        q.id === queryId ? { ...q, ...updates } : q,
      ),
    })),

  addClip: (clip) =>
    set((s) => {
      if (s.clips.some((c) => c.id === clip.id)) return s;
      return { clips: [...s.clips, clip] };
    }),

  setClips: (clips) => set({ clips }),

  reset: () => set(INITIAL),
}));
