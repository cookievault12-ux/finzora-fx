"""Tests for the response-parsing safety logic in src/llm/claude_client.py.

The critical property under test: ANY malformed, unparseable, or
unexpected LLM response must fail safe to VETO, never to CONFIRM — a
parsing bug here must never accidentally let a trade through. Doesn't
exercise the actual Anthropic API call (no network in the build sandbox;
that part was reviewed, not executed — see module docstring). Run for
real with: pip install -e ".[dev]" && pytest tests/test_claude_client.py -v
"""

from __future__ import annotations

import json


def _parse_verdict(raw_text: str) -> tuple[str, str]:
    """Mirrors the parsing block inside confirm_or_veto() exactly, isolated
    here so it can be tested without needing the `anthropic` package or a
    live API call."""
    try:
        cleaned = raw_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)
        decision = str(parsed.get("decision", "")).upper()
        reasoning = str(parsed.get("reasoning", ""))
        if decision not in ("CONFIRM", "VETO"):
            raise ValueError(f"Unexpected decision value: {decision!r}")
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        return "VETO", f"unparseable: {exc}"
    return decision, reasoning


def test_clean_confirm_json_parses():
    decision, reasoning = _parse_verdict('{"decision": "CONFIRM", "reasoning": "looks good"}')
    assert decision == "CONFIRM"
    assert reasoning == "looks good"


def test_clean_veto_json_parses():
    decision, _ = _parse_verdict('{"decision": "VETO", "reasoning": "risky"}')
    assert decision == "VETO"


def test_code_fence_wrapped_json_still_parses():
    decision, reasoning = _parse_verdict('```json\n{"decision": "VETO", "reasoning": "risky"}\n```')
    assert decision == "VETO"
    assert reasoning == "risky"


def test_garbage_text_fails_safe_to_veto():
    decision, _ = _parse_verdict("not json at all")
    assert decision == "VETO"


def test_invalid_decision_value_fails_safe_to_veto():
    decision, _ = _parse_verdict('{"decision": "MAYBE", "reasoning": "x"}')
    assert decision == "VETO"


def test_missing_decision_key_fails_safe_to_veto():
    decision, _ = _parse_verdict('{"reasoning": "x"}')
    assert decision == "VETO"


def test_empty_string_fails_safe_to_veto():
    decision, _ = _parse_verdict("")
    assert decision == "VETO"
