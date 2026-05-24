"use client";

import { useMemo, useState } from "react";
import type { TimelineEvent, EventType } from "@/lib/types";

interface TimelineScrubberProps {
  events: TimelineEvent[];
}

const EVENT_COLORS: Record<EventType, string> = {
  goal: "bg-red-500",
  shot: "bg-orange-400",
  foul: "bg-yellow-400",
  card: "bg-red-600",
  substitution: "bg-blue-400",
  corner: "bg-teal-400",
  offside: "bg-purple-400",
  kickoff: "bg-green-400",
  halftime: "bg-gray-400",
  fulltime: "bg-gray-400",
  other: "bg-gray-500",
};

const EVENT_LABELS: Record<EventType, string> = {
  goal: "Goal",
  shot: "Shot",
  foul: "Foul",
  card: "Card",
  substitution: "Sub",
  corner: "Corner",
  offside: "Offside",
  kickoff: "Kick-off",
  halftime: "Half-time",
  fulltime: "Full-time",
  other: "Event",
};

function formatClock(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function TimelineScrubber({ events }: TimelineScrubberProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  const maxPts = useMemo(() => {
    if (events.length === 0) return 1;
    return Math.max(...events.map((e) => e.pts_ms), 1);
  }, [events]);

  if (events.length === 0) {
    return <div className="relative h-12 rounded-lg bg-gray-800/60" />;
  }

  return (
    <div className="relative">
      {/* Track */}
      <div className="relative h-12 rounded-lg bg-gray-800/60 overflow-visible">
        {/* Baseline */}
        <div className="absolute top-1/2 left-3 right-3 h-px bg-gray-700" />

        {/* Event dots */}
        {events.map((event, index) => {
          const pct = (event.pts_ms / maxPts) * 100;
          const color = EVENT_COLORS[event.type] ?? EVENT_COLORS.other;
          const stableKey = event.id ?? `${event.type}_${event.pts_ms}_${index}`;
          const isHovered = hoveredId === stableKey;

          return (
            <div
              key={stableKey}
              className="absolute top-1/2 -translate-y-1/2 z-10"
              style={{ left: `calc(12px + ${pct}% * (100% - 24px) / 100%)` }}
              onMouseEnter={() => setHoveredId(stableKey)}
              onMouseLeave={() => setHoveredId(null)}
            >
              {/* Dot */}
              <div
                className={`h-3.5 w-3.5 -ml-[7px] rounded-full border-2 border-gray-900 cursor-pointer transition-transform ${color} ${
                  isHovered ? "scale-150" : ""
                } ${event.type === "goal" ? "animate-pulse-dot" : ""}`}
              />

              {/* Tooltip */}
              {isHovered && (
                <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-50 whitespace-nowrap rounded bg-gray-900 px-3 py-1.5 text-xs shadow-lg border border-gray-700">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block h-2 w-2 rounded-full ${color}`}
                    />
                    <span className="font-medium text-white">
                      {EVENT_LABELS[event.type] ?? event.type}
                    </span>
                    <span className="text-gray-400">
                      {event.match_clock || formatClock(event.pts_ms)}
                    </span>
                  </div>
                  <p className="mt-1 text-gray-300 max-w-[240px] truncate">
                    {event.description}
                  </p>
                  {event.player && (
                    <p className="text-gray-500">{event.player}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Time labels */}
      <div className="mt-1 flex justify-between px-3 text-[10px] tabular-nums text-gray-600">
        <span>0:00</span>
        <span>{formatClock(maxPts)}</span>
      </div>
    </div>
  );
}
