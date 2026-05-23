"use client";

import { useEffect, useRef, use } from "react";
import { useSessionStore } from "@/lib/store";
import { connectSession } from "@/lib/ws";
import { fetchSession, fetchTimeline, fetchClips } from "@/lib/api";
import { toEmbedUrl } from "@/lib/youtube";
import MatchHeader from "@/components/MatchHeader";
import Commentary from "@/components/Commentary";
import WhatIfComposer from "@/components/WhatIfComposer";
import ClipTray from "@/components/ClipTray";
import TimelineScrubber from "@/components/TimelineScrubber";

interface SessionPageProps {
  params: Promise<{ id: string }>;
}

export default function SessionPage({ params }: SessionPageProps) {
  const { id: sessionId } = use(params);
  const disconnectRef = useRef<(() => void) | null>(null);

  const setSession = useSessionStore((s) => s.setSession);
  const setWsConnected = useSessionStore((s) => s.setWsConnected);
  const updateMatchState = useSessionStore((s) => s.updateMatchState);
  const addCommentary = useSessionStore((s) => s.addCommentary);
  const addEvent = useSessionStore((s) => s.addEvent);
  const setEvents = useSessionStore((s) => s.setEvents);
  const addQuery = useSessionStore((s) => s.addQuery);
  const updateQuery = useSessionStore((s) => s.updateQuery);
  const addClip = useSessionStore((s) => s.addClip);
  const setClips = useSessionStore((s) => s.setClips);

  const sourceUrl = useSessionStore((s) => s.sourceUrl);
  const matchState = useSessionStore((s) => s.matchState);
  const commentary = useSessionStore((s) => s.commentary);
  const events = useSessionStore((s) => s.events);
  const queries = useSessionStore((s) => s.queries);
  const clips = useSessionStore((s) => s.clips);
  const wsConnected = useSessionStore((s) => s.wsConnected);

  /* ── Bootstrap: set session, fetch initial data, connect WS ── */
  useEffect(() => {
    setSession(sessionId, "");

    // Fetch session to get source_url
    fetchSession(sessionId)
      .then((data) => {
        if (data.source_url) {
          setSession(sessionId, data.source_url);
        }
      })
      .catch(() => {});

    // Fetch initial timeline + clips
    fetchTimeline(sessionId)
      .then((data) => {
        if (data.match_state) updateMatchState(data.match_state);
        if (data.events) setEvents(data.events);
      })
      .catch(() => {});

    fetchClips(sessionId)
      .then((data) => {
        if (data) setClips(data);
      })
      .catch(() => {
        // No clips yet
      });

    // Connect WebSocket
    const disconnect = connectSession(sessionId, {
      onMatchState: (data) => {
        updateMatchState(data);
        // Capture source_url if delivered via match state
        const raw = data as unknown as Record<string, unknown>;
        if (typeof raw.source_url === "string" && raw.source_url) {
          setSession(sessionId, raw.source_url);
        }
      },
      onCommentary: (line) => addCommentary(line),
      onEvent: (event) => addEvent(event),
      onQueryProgress: (data) => {
        if (data.id) {
          updateQuery(data.id, data);
        }
      },
      onClipReady: (clip) => {
        addClip(clip);
        // Also mark the query as complete
        if (clip.query_id) {
          updateQuery(clip.query_id, {
            status: "complete",
            clip_id: clip.id,
          });
        }
      },
      onOpen: () => setWsConnected(true),
      onClose: () => setWsConnected(false),
    });

    disconnectRef.current = disconnect;

    return () => {
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const embedUrl = sourceUrl ? toEmbedUrl(sourceUrl) : null;

  return (
    <div className="flex min-h-screen flex-col bg-gray-950">
      {/* ── Top nav ── */}
      <header className="flex items-center justify-between border-b border-gray-800 px-6 py-3">
        <a href="/" className="text-lg font-bold text-white hover:text-gray-300 transition-colors">
          What If
        </a>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="font-mono">{sessionId.slice(0, 8)}</span>
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              wsConnected ? "bg-emerald-400" : "bg-red-400 animate-pulse"
            }`}
          />
          <span>{wsConnected ? "Live" : "Connecting..."}</span>
        </div>
      </header>

      {/* ── Main content ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── Left: Video + Timeline ── */}
        <div className="flex w-[65%] flex-col gap-4 p-4">
          {/* Video embed */}
          <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-gray-900 border border-gray-800">
            {embedUrl ? (
              <iframe
                src={embedUrl}
                title="Live match"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                className="absolute inset-0 h-full w-full"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center">
                <div className="flex flex-col items-center gap-3 text-gray-500">
                  <svg className="h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
                  </svg>
                  <span className="text-sm">Waiting for video feed...</span>
                  <span className="text-xs text-gray-600">
                    The stream URL will be set once the session starts ingesting.
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* Timeline scrubber */}
          <TimelineScrubber events={events} />
        </div>

        {/* ── Right: Match info + Commentary + Composer + Clips ── */}
        <div className="flex w-[35%] flex-col gap-3 border-l border-gray-800 p-4 overflow-hidden">
          {/* Match header */}
          <MatchHeader matchState={matchState} wsConnected={wsConnected} />

          {/* Commentary panel */}
          <div className="flex flex-1 flex-col overflow-hidden rounded-lg border border-gray-800 bg-gray-900/40 p-3">
            <h2 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  wsConnected ? "bg-emerald-400" : "bg-gray-600"
                }`}
              />
              Live Commentary
            </h2>
            <Commentary lines={commentary} />
          </div>

          {/* What-if composer */}
          <div className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
              Ask a What-If
            </h2>
            <WhatIfComposer sessionId={sessionId} />
          </div>

          {/* Clip tray */}
          <div className="flex max-h-[30%] flex-col overflow-hidden rounded-lg border border-gray-800 bg-gray-900/40 p-3">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
              Clips
            </h2>
            <div className="flex-1 overflow-y-auto">
              <ClipTray queries={queries} clips={clips} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
