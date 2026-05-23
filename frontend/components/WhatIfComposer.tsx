"use client";

import { useState, useCallback } from "react";
import { submitQuery } from "@/lib/api";
import { useSessionStore } from "@/lib/store";

interface WhatIfComposerProps {
  sessionId: string;
}

const SUGGESTIONS = [
  "What if that shot had gone in?",
  "What if the pass had been intercepted?",
  "What if the keeper had come out?",
];

export default function WhatIfComposer({ sessionId }: WhatIfComposerProps) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const addQuery = useSessionStore((s) => s.addQuery);

  const handleSubmit = useCallback(
    async (queryText: string) => {
      const trimmed = queryText.trim();
      if (!trimmed || submitting) return;

      setSubmitting(true);
      setError(null);

      try {
        const query = await submitQuery(sessionId, trimmed);
        addQuery(query);
        setText("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to submit query");
      } finally {
        setSubmitting(false);
      }
    },
    [sessionId, submitting, addQuery],
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Input row */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSubmit(text);
        }}
        className="flex gap-2"
      >
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="What if..."
          disabled={submitting}
          className="flex-1 rounded-lg border border-gray-700 bg-gray-800 px-4 py-2.5 text-sm text-white placeholder-gray-500 outline-none transition-colors focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={submitting || !text.trim()}
          className="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {submitting ? (
            <span className="flex items-center gap-2">
              <Spinner />
              Sending
            </span>
          ) : (
            "Ask"
          )}
        </button>
      </form>

      {/* Error */}
      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}

      {/* Suggestion chips */}
      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => handleSubmit(s)}
            disabled={submitting}
            className="rounded-full border border-gray-700 bg-gray-800/50 px-3 py-1 text-xs text-gray-300 transition-colors hover:border-indigo-500 hover:text-white disabled:opacity-40"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="h-4 w-4 animate-spin"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}
