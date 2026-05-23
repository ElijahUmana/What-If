"use client";

import type { MatchState } from "@/lib/types";

interface MatchHeaderProps {
  matchState: MatchState | null;
  wsConnected: boolean;
}

export default function MatchHeader({
  matchState,
  wsConnected,
}: MatchHeaderProps) {
  if (!matchState) {
    return (
      <div className="flex items-center justify-between rounded-lg bg-gray-800/60 px-5 py-3 backdrop-blur">
        <span className="text-sm text-gray-400">
          Waiting for match data...
        </span>
        <ConnectionDot connected={wsConnected} />
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between rounded-lg bg-gray-800/60 px-5 py-3 backdrop-blur">
      {/* Home */}
      <div className="flex items-center gap-3">
        {matchState.home_logo_url && (
          <img
            src={matchState.home_logo_url}
            alt={matchState.home_team}
            className="h-7 w-7 object-contain"
          />
        )}
        <span className="text-lg font-semibold text-white">
          {matchState.home_team}
        </span>
      </div>

      {/* Score + Clock */}
      <div className="flex flex-col items-center gap-0.5">
        <div className="flex items-center gap-3">
          <span className="text-3xl font-bold tabular-nums text-white">
            {matchState.home_score}
          </span>
          <span className="text-xl text-gray-500">&ndash;</span>
          <span className="text-3xl font-bold tabular-nums text-white">
            {matchState.away_score}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span className="uppercase tracking-wider">
            {matchState.period}
          </span>
          <span className="font-mono">{matchState.clock}</span>
          <ConnectionDot connected={wsConnected} />
        </div>
      </div>

      {/* Away */}
      <div className="flex items-center gap-3">
        <span className="text-lg font-semibold text-white">
          {matchState.away_team}
        </span>
        {matchState.away_logo_url && (
          <img
            src={matchState.away_logo_url}
            alt={matchState.away_team}
            className="h-7 w-7 object-contain"
          />
        )}
      </div>
    </div>
  );
}

function ConnectionDot({ connected }: { connected: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 rounded-full ${
        connected ? "bg-emerald-400" : "bg-red-400 animate-pulse"
      }`}
      title={connected ? "Live" : "Reconnecting..."}
    />
  );
}
