"""Claude synthesis layer for the signal engine (Phase 4).

IMPORTANT safety design: Claude is a CONFIRM/VETO layer on top of the
deterministic trend-following signal (src/signals/trend_following.py), NOT
an independent signal generator. It is only ever called when the
mechanical layer has already produced a candidate LONG or SHORT — never
when the mechanical layer says NO_TRADE (that's final immediately, no LLM
call, no cost). Given a candidate trade, Claude can only CONFIRM it or
VETO it down to NO_TRADE; it can never flip LONG to SHORT or invent a
direction the mechanical layer didn't support. This keeps "NO_TRADE is
first-class, the risk layer is never bypassable" true even with an LLM in
the loop, and means a parsing failure or API error can safely default to
VETO (NO_TRADE) rather than blindly executing a trade.

Uses claude-haiku-4-5 — a cost-conscious choice for a repetitive,
structured confirm/veto task, not a claim that this is the hardest
reasoning problem in the system. Dual-LLM voting (a second model
cross-checking Claude) is deliberately deferred — see PHASE0_REPORT.md
section 21.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
PROMPT_VERSION = "signal-confirm-veto-v1"


@dataclass
class LlmVerdict:
    decision: str  # CONFIRM | VETO
    reasoning: str
    raw_response: str | None  # for the llm_analysis audit trail


def _build_prompt(context: dict) -> str:
    return f"""You are a risk-review layer for an FX paper-trading signal engine. A deterministic \
rule-based strategy has already produced a candidate trade below. Your ONLY job is to CONFIRM it \
or VETO it — you cannot change the direction, entry, stop, or target, and you cannot invent a trade \
if none exists. If you're at all unsure, VETO. Reply with ONLY a JSON object, no other text: \
{{"decision": "CONFIRM" or "VETO", "reasoning": "one or two sentences"}}.

Candidate trade:
Instrument: {context['instrument']}
Direction: {context['direction']}
Mechanical reason: {context['mechanical_reason']}
Entry: {context['entry_price']}, Stop: {context['stop_loss']}, Target: {context['take_profit_1']}, Risk/Reward: {context['risk_reward']}

Sub-scores (0-100, higher is more favorable; null means not available):
Technical: {context['technical_score']}
Regime: {context['regime_score']} (labels: {context['regime_labels']}, confidence: {context['regime_confidence']})
Macro backdrop: {context['macro_score']} (null/50 only — no directional macro model exists yet, treat as presence/freshness only)
Geopolitical: {context['geopolitical_score']} (100 = no notable recent events for this pair's currencies, lower = a significant recent event was detected)
Execution (live spread quality): {context['execution_score']}
Risk/reward: {context['risk_reward_score']}
Composite: {context['composite_score']}

Recent geopolitical events for this pair's currencies (may be empty):
{context['recent_geo_events']}
"""


def confirm_or_veto(context: dict) -> LlmVerdict:
    """Calls Claude once with the candidate trade + all sub-scores. Any
    failure (API error, malformed/unparseable JSON, missing decision
    field) fails safe to VETO — never to CONFIRM. This function should
    only ever be called when the mechanical layer already produced a
    candidate LONG/SHORT; callers must not use this to originate a
    direction."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return LlmVerdict(decision="VETO", reasoning="ANTHROPIC_API_KEY not configured.", raw_response=None)

    prompt = _build_prompt(context)
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text if response.content else ""
    except Exception as exc:  # noqa: BLE001 — a broken LLM call must never crash the signal cycle
        logger.exception("Claude confirm/veto call failed")
        return LlmVerdict(decision="VETO", reasoning=f"LLM call failed: {exc}", raw_response=None)

    try:
        # Claude is asked for pure JSON, but strip any accidental code-fence
        # wrapping before parsing rather than failing on it outright.
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)
        decision = str(parsed.get("decision", "")).upper()
        reasoning = str(parsed.get("reasoning", ""))
        if decision not in ("CONFIRM", "VETO"):
            raise ValueError(f"Unexpected decision value: {decision!r}")
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Could not parse Claude confirm/veto response (%s): %r", exc, raw_text)
        return LlmVerdict(
            decision="VETO", reasoning=f"Unparseable LLM response, defaulting to VETO: {exc}",
            raw_response=raw_text,
        )

    return LlmVerdict(decision=decision, reasoning=reasoning, raw_response=raw_text)
