"""RetrievalAgent -- reranks candidate moments to find the user's anchor."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agents._lib.gmi import reason as gmi_reason
from agents._lib.trace import trace_span

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parents[2] / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "retrieval.rerank.md").read_text()


def _build_candidates_block(
    events: list[dict], summaries: list[dict]
) -> list[dict]:
    """Merge events and summaries into a flat candidate list for the prompt."""
    candidates = []
    for i, ev in enumerate(events):
        candidates.append(
            {
                "id": ev.get("id", f"event_{i}"),
                "kind": "event",
                "text": ev.get("description", ev.get("type", "")),
                "pts_ms": ev.get("start_pts_ms", ev.get("pts_ms", 0)),
                "similarity": ev.get("similarity", 0.0),
                "surrounding_context": ev.get("surrounding_context", ""),
            }
        )
    for i, s in enumerate(summaries):
        candidates.append(
            {
                "id": s.get("id", f"summary_{i}"),
                "kind": "summary",
                "text": s.get("narrative", s.get("key_action", "")),
                "pts_ms": s.get("pts_ms", s.get("window_start_ms", 0)),
                "similarity": s.get("similarity", 0.0),
                "surrounding_context": s.get("surrounding_context", ""),
            }
        )
    # Sort by pts_ms for chronological ordering, take top 20
    candidates.sort(key=lambda c: c.get("pts_ms", 0))
    return candidates[:20]


async def resolve_query(
    query_text: str,
    events: list[dict],
    summaries: list[dict],
    match_state: dict,
    live_now_pts_ms: int = 0,
    session_id: str = "",
) -> dict:
    """Resolve a user 'what if' query to an anchor moment.

    Returns:
        {anchor_id, anchor_pts_ms, window_start_ms, window_end_ms,
         change_type, entities_referenced, intent_clarity,
         clarification_options, reasoning}
    """
    with trace_span("retrieval", "resolve_query", session_id=session_id) as span:
        candidates = _build_candidates_block(events, summaries)
        user_block = (
            f"USER_PROMPT: {query_text}\n\n"
            f"CURRENT_MATCH_STATE: {json.dumps(match_state)}\n\n"
            f"LIVE_NOW_PTS_MS: {live_now_pts_ms}\n\n"
            f"CANDIDATES:\n{json.dumps(candidates, indent=2)}"
        )

        result = gmi_reason(SYSTEM_PROMPT, user_block)
        span["payload"]["model"] = "deepseek-ai/DeepSeek-V4-Flash"
        span["payload"]["intent_clarity"] = result.get("intent_clarity")
        span["payload"]["change_type"] = result.get("change_type")
        span["payload"]["candidate_count"] = len(candidates)
        return result
