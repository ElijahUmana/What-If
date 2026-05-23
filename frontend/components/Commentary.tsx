"use client";

import { useEffect, useRef } from "react";
import type { CommentaryLine } from "@/lib/types";

interface CommentaryProps {
  lines: CommentaryLine[];
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

function lineAccent(type?: CommentaryLine["type"]): string {
  switch (type) {
    case "highlight":
      return "border-l-amber-400";
    case "analysis":
      return "border-l-sky-400";
    default:
      return "border-l-gray-600";
  }
}

export default function Commentary({ lines }: CommentaryProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines.length]);

  if (lines.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-gray-500">
        Commentary will appear here once the match feed connects.
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col gap-1 overflow-y-auto pr-1">
      {lines.map((line, i) => (
        <div
          key={line.id ?? i}
          className={`border-l-2 pl-3 py-1.5 ${lineAccent(line.type)} animate-slide-up`}
        >
          <p className="text-sm leading-relaxed text-gray-200">{line.text}</p>
          <span className="mt-0.5 block text-[10px] tabular-nums text-gray-500">
            {formatTime(line.timestamp)}
            {line.pts_ms != null && (
              <> &middot; {Math.round(line.pts_ms / 1000)}s</>
            )}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
