"use client";

import { useState, useCallback, useMemo } from "react";
import type { Query, Clip, QueryStatus } from "@/lib/types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const STORAGE_PREFIX = "/tmp/whatif_storage/sessions/";

/** Derive a playable video URL from a Clip object. */
function clipVideoUrl(clip: Clip): string {
  // If the backend already gave us a full video_url, use it.
  if (clip.video_url) return clip.video_url;

  // Otherwise, derive from storage_uri via the gateway serve_clip endpoint.
  if (clip.storage_uri) {
    const relative = clip.storage_uri.startsWith(STORAGE_PREFIX)
      ? clip.storage_uri.slice(STORAGE_PREFIX.length)
      : clip.storage_uri;
    return `${API_BASE}/api/clips/${relative}`;
  }

  return "";
}

/** Get the prompt/description text for display. */
function clipPrompt(clip: Clip): string {
  return clip.prompt_text ?? clip.prompt ?? "";
}

interface ClipTrayProps {
  queries: Query[];
  clips: Clip[];
}

const STAGE_ORDER: QueryStatus[] = [
  "submitted",
  "resolving",
  "retrieving",
  "composing",
  "generating",
  "validating",
  "compositing",
  "complete",
];

function stageIndex(status: QueryStatus): number {
  const idx = STAGE_ORDER.indexOf(status);
  return idx === -1 ? 0 : idx;
}

function progressPct(query: Query): number {
  if (query.progress_pct != null) return query.progress_pct;
  if (query.status === "complete") return 100;
  if (query.status === "failed") return 0;
  return Math.round((stageIndex(query.status) / (STAGE_ORDER.length - 1)) * 100);
}

function stageLabel(query: Query): string {
  if (query.stage_label) return query.stage_label;
  switch (query.status) {
    case "submitted":
      return "Queued";
    case "resolving":
      return "Finding the moment...";
    case "retrieving":
      return "Pulling frames...";
    case "composing":
      return "Writing Veo prompt...";
    case "generating":
      return "Generating video...";
    case "validating":
      return "Checking continuity...";
    case "compositing":
      return "Compositing clip...";
    case "complete":
      return "Ready";
    case "failed":
      return "Failed";
    default:
      return query.status;
  }
}

export default function ClipTray({ queries, clips }: ClipTrayProps) {
  const [playingClipId, setPlayingClipId] = useState<string | null>(null);

  const clipForQuery = useCallback(
    (queryId: string): Clip | undefined =>
      clips.find((c) => c.query_id === queryId),
    [clips],
  );

  const playingClip = playingClipId
    ? clips.find((c) => c.id === playingClipId) ?? null
    : null;

  if (queries.length === 0) {
    return (
      <div className="flex items-center justify-center py-6 text-sm text-gray-500">
        Your what-if clips will appear here.
      </div>
    );
  }

  return (
    <>
      <div className="flex flex-col gap-2 overflow-y-auto">
        {queries.map((query) => {
          const clip = query.clip_id
            ? clipForQuery(query.id)
            : undefined;
          const done = query.status === "complete" && clip;
          const failed = query.status === "failed";

          return (
            <div
              key={query.id}
              className="animate-slide-up rounded-lg border border-gray-700/50 bg-gray-800/40 p-3"
            >
              {/* Prompt text */}
              <p className="text-sm text-gray-200 line-clamp-2">
                {query.text}
              </p>

              {/* In-progress state */}
              {!done && !failed && (
                <div className="mt-2">
                  <div className="flex items-center justify-between text-[10px] text-gray-400">
                    <span>{stageLabel(query)}</span>
                    <span className="tabular-nums">
                      {progressPct(query)}%
                    </span>
                  </div>
                  <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-gray-700">
                    <div
                      className="h-full rounded-full bg-indigo-500 transition-all duration-500 animate-progress-fill"
                      style={{ width: `${progressPct(query)}%` }}
                    />
                  </div>
                </div>
              )}

              {/* Failed state */}
              {failed && (
                <p className="mt-2 text-xs text-red-400">
                  {query.error ?? "Generation failed"}
                </p>
              )}

              {/* Completed clip */}
              {done && clip && (
                <div className="mt-2 flex items-center gap-2">
                  {/* Thumbnail */}
                  <div className="relative h-14 w-24 flex-shrink-0 overflow-hidden rounded bg-gray-700">
                    {clip.thumbnail_url ? (
                      <img
                        src={clip.thumbnail_url}
                        alt="Clip thumbnail"
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-xs text-gray-500">
                        Preview
                      </div>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => setPlayingClipId(clip.id)}
                    className="flex items-center gap-1.5 rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-indigo-500"
                  >
                    <PlayIcon />
                    Play
                  </button>

                  <span className="text-[10px] tabular-nums text-gray-500">
                    {(clip.duration_ms / 1000).toFixed(1)}s
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Video overlay */}
      {playingClip && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={() => setPlayingClipId(null)}
        >
          <div
            className="relative w-full max-w-3xl rounded-xl bg-gray-900 p-2 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setPlayingClipId(null)}
              className="absolute -top-3 -right-3 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-gray-800 text-gray-400 transition-colors hover:text-white border border-gray-700"
            >
              &times;
            </button>
            <video
              src={clipVideoUrl(playingClip)}
              controls
              autoPlay
              className="w-full rounded-lg"
            />
            <p className="mt-2 px-2 pb-1 text-sm text-gray-300">
              {clipPrompt(playingClip)}
            </p>
          </div>
        </div>
      )}
    </>
  );
}

function PlayIcon() {
  return (
    <svg
      className="h-3.5 w-3.5"
      viewBox="0 0 16 16"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M4 2.5v11l9-5.5L4 2.5z" />
    </svg>
  );
}
