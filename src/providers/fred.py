"""FRED (Federal Reserve Economic Data) client — Phase 3 macro data.

FRED is completely free (no paid tier), 120 requests/min with an API key,
so there's no cost/quota concern here (see Phase 3 research). This is a
thin client, not a MarketDataProvider — FRED serves single-value economic
time series (CPI, unemployment, yields, ...), not FX OHLC bars, so it
doesn't share the FX-specific interface in src/providers/base.py.

NOT executed in the build sandbox (no outbound network access there — see
src/data/ingestion.py's module docstring for the same caveat). Smoke-test
against a real FRED response before relying on this.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

_BASE_URL = "https://api.stlouisfed.org/fred"


@dataclass
class FredObservation:
    date: dt.datetime  # UTC midnight of the observation date
    value: Decimal | None  # None when FRED reports "." (no data for this period)


def _parse_value(raw: str) -> Decimal | None:
    """FRED uses the literal string "." for a missing observation (e.g. a
    series that hasn't published this period's figure yet). Map that to
    None rather than 0 or skipping the row — a missing macro print is a
    real, distinct fact, not a zero value (mirrors src/data/quality.py's
    "never fabricate" principle)."""
    if raw == ".":
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


class FredClient:
    name = "fred"

    def __init__(self, *, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("FRED_API_KEY")
        if not self._api_key:
            raise RuntimeError("FRED_API_KEY must be set (see .env.example).")
        self._client = httpx.Client(base_url=_BASE_URL, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FredClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get_series_observations(
        self,
        series_id: str,
        *,
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
        limit: int | None = None,
    ) -> list[FredObservation]:
        """Returns observations for one FRED series, oldest first (FRED's
        default sort), unless `limit` is given, in which case the most
        recent `limit` observations are returned (used for "just get me the
        latest print" callers)."""
        params: dict = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
        }
        if start is not None:
            params["observation_start"] = start.strftime("%Y-%m-%d")
        if end is not None:
            params["observation_end"] = end.strftime("%Y-%m-%d")
        if limit is not None:
            params["limit"] = limit
            params["sort_order"] = "desc"

        resp = self._client.get("/series/observations", params=params)
        resp.raise_for_status()
        data = resp.json()

        observations = [
            FredObservation(
                date=dt.datetime.strptime(obs["date"], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc),
                value=_parse_value(obs["value"]),
            )
            for obs in data.get("observations", [])
        ]
        if limit is not None:
            observations.reverse()  # restore oldest-first for a consistent return shape
        return observations

    def get_latest_observation(self, series_id: str) -> FredObservation | None:
        obs = self.get_series_observations(series_id, limit=1)
        return obs[-1] if obs else None
