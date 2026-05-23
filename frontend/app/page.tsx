"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { createSession } from "@/lib/api";

export default function LandingPage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);

    try {
      const session = await createSession(trimmed);
      router.push(`/session/${session.session_id}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create session",
      );
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-gray-950 px-4">
      {/* Background glow */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-1/2 top-1/3 h-[600px] w-[600px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-600/10 blur-[120px]" />
        <div className="absolute left-1/3 top-2/3 h-[400px] w-[400px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-purple-600/8 blur-[100px]" />
      </div>

      <div className="relative z-10 flex w-full max-w-xl flex-col items-center gap-8">
        {/* Logo / Title */}
        <div className="flex flex-col items-center gap-3">
          <h1 className="text-6xl font-bold tracking-tight text-white">
            What If
          </h1>
          <p className="max-w-md text-center text-lg text-gray-400">
            Ask what-if about a live football match. Get the answer in video.
          </p>
        </div>

        {/* Input form */}
        <form
          onSubmit={handleSubmit}
          className="flex w-full flex-col gap-3 sm:flex-row"
        >
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste a YouTube live match URL"
            required
            disabled={loading}
            className="flex-1 rounded-xl border border-gray-700 bg-gray-900 px-5 py-3.5 text-sm text-white placeholder-gray-500 outline-none transition-colors focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={loading || !url.trim()}
            className="rounded-xl bg-indigo-600 px-7 py-3.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
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
                Connecting...
              </span>
            ) : (
              "Start watching"
            )}
          </button>
        </form>

        {/* Error */}
        {error && (
          <p className="text-sm text-red-400">{error}</p>
        )}

        {/* Feature hints */}
        <div className="grid w-full grid-cols-3 gap-4 pt-4">
          <FeatureCard
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
              </svg>
            }
            title="Live match"
            description="Watch the broadcast as it happens"
          />
          <FeatureCard
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
              </svg>
            }
            title="AI commentary"
            description="Real-time analysis by agents"
          />
          <FeatureCard
            icon={
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
              </svg>
            }
            title="What-if video"
            description="Generate alternate realities with Veo"
          />
        </div>
      </div>
    </div>
  );
}

interface FeatureCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
}

function FeatureCard({ icon, title, description }: FeatureCardProps) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-xl border border-gray-800 bg-gray-900/50 p-4 text-center">
      <div className="text-indigo-400">{icon}</div>
      <h3 className="text-sm font-medium text-white">{title}</h3>
      <p className="text-xs text-gray-500">{description}</p>
    </div>
  );
}
