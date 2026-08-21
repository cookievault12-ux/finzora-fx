"""Rule-based market regime classification (spec Phase 2, market_regimes).

Deliberately deterministic, not statistical/ML — every label traces back to
a named threshold constant below, so a regime label in the audit trail is
always explainable ("avg ADX was 31.2, >= TREND_ADX_THRESHOLD of 25, hence
TRENDING") rather than an opaque model output. This was an explicit project
choice over a Hidden Markov Model approach for Phase 2.

Only two axes are classified: TRENDING/RANGING (trend strength, from ADX)
and HIGH_VOLATILITY/LOW_VOLATILITY (from realized return dispersion). A
RISK_ON/RISK_OFF axis is NOT included here even though the market_regimes
table's own DDL comment shows it as an example label — that needs VIX/DXY/
cross-asset context (spec Phase 3: macro & geopolitical intelligence), and
none of that is ingested yet as of Phase 2. Fabricating a risk-sentiment
label from FX price data alone would be exactly the kind of invented
financial signal the project's data-quality principles rule out elsewhere
(src/data/quality.py) — so it's left for Phase 3 once the cross-asset feed
that actually supports it exists.

The two thresholds below are literature-informed starting points (ADX >= 25
is Wilder's own "trending" cutoff; the volatility cutoff is a reasonable H1
FX heuristic), NOT calibrated against this project's own historical data
yet — there isn't enough live history to compute real percentiles. Revisit
both once a few months of live features have accumulated.
"""

from __future__ import annotations

METHODOLOGY_VERSION = "rule_based_v1"

TREND_ADX_THRESHOLD = 25.0
HIGH_VOL_RETURN_STDDEV_THRESHOLD = 0.0015  # per-bar return stddev (H1), fractional not %


def _axis_confidence(value: float, threshold: float) -> float:
    """0.0 right at the threshold (most ambiguous), approaching 1.0 the
    further the value sits from it on either side. Purely a function of the
    two numbers involved — no hidden state, fully reproducible."""
    if threshold == 0:
        return 0.0
    return max(0.0, min(1.0, abs(value - threshold) / threshold))


def classify_regime(features_by_pair: dict[str, dict]) -> tuple[list[str], float | None]:
    """features_by_pair: {symbol: feature_dict} for however many of the 8
    majors have a current feature row (H1 timeframe expected). Averages
    adx_14 and return_stddev_20 across pairs that have them, and classifies
    against the two fixed thresholds above.

    Returns (regime_labels, confidence). If no pair has both indicators
    computed yet (e.g. still warming up on a fresh deployment), returns
    ([], None) rather than a fabricated label — an empty/unknown regime is
    honest; a guessed one is not."""
    adx_values = [f["adx_14"] for f in features_by_pair.values() if f.get("adx_14") is not None]
    vol_values = [f["return_stddev_20"] for f in features_by_pair.values() if f.get("return_stddev_20") is not None]

    if not adx_values or not vol_values:
        return [], None

    avg_adx = sum(adx_values) / len(adx_values)
    avg_vol = sum(vol_values) / len(vol_values)

    labels = [
        "TRENDING" if avg_adx >= TREND_ADX_THRESHOLD else "RANGING",
        "HIGH_VOLATILITY" if avg_vol >= HIGH_VOL_RETURN_STDDEV_THRESHOLD else "LOW_VOLATILITY",
    ]
    trend_conf = _axis_confidence(avg_adx, TREND_ADX_THRESHOLD)
    vol_conf = _axis_confidence(avg_vol, HIGH_VOL_RETURN_STDDEV_THRESHOLD)
    confidence = round((trend_conf + vol_conf) / 2, 4)
    return labels, confidence
