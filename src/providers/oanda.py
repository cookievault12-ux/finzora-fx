"""OANDA MarketDataProvider implementation.

Uses the OANDA v20 REST API. Practice (demo) environment by default per
config/providers.yaml and OANDA_ENVIRONMENT in .env — never switches to
live pricing/execution on its own.

OANDA's granularity strings happen to match this project's Timeframe enum
values exactly (D, H4, H1, M15, M5), so mapping is close to 1:1.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

import httpx

from src.market.types import InstrumentInfo, MarketStatus, OHLCBar, Quote, Tick, Timeframe
from src.providers.base import MarketDataProvider

_BASE_URLS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}

_TIMEFRAME_TO_GRANULARITY = {
    Timeframe.D1: "D",
    Timeframe.H4: "H4",
    Timeframe.H1: "H1",
    Timeframe.M15: "M15",
    Timeframe.M5: "M5",
}

# OANDA hard-caps a single candles request at 5000 bars — see PHASE0_REPORT.md
# section 4. Callers pulling multi-year history must paginate; this class
# does that internally in get_historical_prices.
_MAX_CANDLES_PER_REQUEST = 5000


def _to_oanda_symbol(instrument: str) -> str:
    """'EUR/USD' -> 'EUR_USD'."""
    return instrument.replace("/", "_")


def _from_oanda_symbol(symbol: str) -> str:
    """'EUR_USD' -> 'EUR/USD'."""
    return symbol.replace("_", "/")


class OandaProvider(MarketDataProvider):
    name = "oanda"

    def __init__(self, *, token: str | None = None, account_id: str | None = None, environment: str | None = None):
        self._token = token or os.environ.get("OANDA_API_TOKEN")
        self._account_id = account_id or os.environ.get("OANDA_ACCOUNT_ID")
        self._environment = environment or os.environ.get("OANDA_ENVIRONMENT", "practice")
        if not self._token or not self._account_id:
            raise RuntimeError(
                "OANDA_API_TOKEN and OANDA_ACCOUNT_ID must be set (see .env.example)."
            )
        if self._environment not in _BASE_URLS:
            raise ValueError(f"Unknown OANDA environment: {self._environment!r}")
        self._base_url = _BASE_URLS[self._environment]
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OandaProvider":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- MarketDataProvider interface -----------------------------------

    def get_instruments(self) -> list[InstrumentInfo]:
        resp = self._client.get(f"/v3/accounts/{self._account_id}/instruments")
        resp.raise_for_status()
        data = resp.json()
        return [
            InstrumentInfo(
                symbol=_from_oanda_symbol(i["name"]),
                asset_class="FX",
                is_tradeable=True,
                provider_instrument_id=i["name"],
            )
            for i in data.get("instruments", [])
            if i.get("type") == "CURRENCY"
        ]

    def get_historical_prices(
        self,
        instrument: str,
        timeframe: Timeframe,
        start: dt.datetime,
        end: dt.datetime,
    ) -> list[OHLCBar]:
        granularity = _TIMEFRAME_TO_GRANULARITY[timeframe]
        symbol = _to_oanda_symbol(instrument)
        bars: list[OHLCBar] = []
        cursor = start
        while cursor < end:
            resp = self._client.get(
                f"/v3/instruments/{symbol}/candles",
                params={
                    "granularity": granularity,
                    "from": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "count": _MAX_CANDLES_PER_REQUEST,
                    "price": "M",  # midpoint OHLC; use bid/ask via get_bid_ask for spread
                },
            )
            resp.raise_for_status()
            candles = resp.json().get("candles", [])
            if not candles:
                break
            for c in candles:
                if not c.get("complete", True):
                    continue
                mid = c["mid"]
                ts = dt.datetime.strptime(c["time"][:19], "%Y-%m-%dT%H:%M:%S").replace(
                    tzinfo=dt.timezone.utc
                )
                bars.append(
                    OHLCBar(
                        instrument=instrument,
                        timeframe=timeframe,
                        ts=ts,
                        open=Decimal(mid["o"]),
                        high=Decimal(mid["h"]),
                        low=Decimal(mid["l"]),
                        close=Decimal(mid["c"]),
                        volume=Decimal(str(c.get("volume", 0))),
                        provider=self.name,
                    )
                )
            last_ts = dt.datetime.strptime(candles[-1]["time"][:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=dt.timezone.utc
            )
            if last_ts <= cursor:
                break  # safety: avoid infinite loop if OANDA returns no forward progress
            cursor = last_ts + dt.timedelta(seconds=1)
            if len(candles) < _MAX_CANDLES_PER_REQUEST:
                break
        return bars

    def get_realtime_prices(self, instruments: list[str]) -> list[Quote]:
        symbols = ",".join(_to_oanda_symbol(i) for i in instruments)
        resp = self._client.get(
            f"/v3/accounts/{self._account_id}/pricing", params={"instruments": symbols}
        )
        resp.raise_for_status()
        quotes = []
        for p in resp.json().get("prices", []):
            ts = dt.datetime.strptime(p["time"][:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=dt.timezone.utc
            )
            quotes.append(
                Quote(
                    instrument=_from_oanda_symbol(p["instrument"]),
                    ts=ts,
                    bid=Decimal(p["bids"][0]["price"]),
                    ask=Decimal(p["asks"][0]["price"]),
                    provider=self.name,
                )
            )
        return quotes

    def get_bid_ask(self, instrument: str) -> Quote:
        quotes = self.get_realtime_prices([instrument])
        if not quotes:
            raise LookupError(f"No price returned for {instrument}")
        return quotes[0]

    def get_spreads(self, instruments: list[str]) -> dict[str, float]:
        return {q.instrument: float(q.spread) for q in self.get_realtime_prices(instruments)}

    def get_ticks(self, instrument: str, start: dt.datetime, end: dt.datetime) -> list[Tick]:
        # OANDA's public API does not expose historical tick-by-tick data —
        # its finest granularity is S5 (5-second) candles. Per spec section 17,
        # tick data is optional; this raises rather than silently degrading.
        raise NotImplementedError(
            "OANDA does not provide historical tick data via the v20 API; "
            "use 5-second candles (get_historical_prices is not wired for S5 "
            "yet) or a tick-capable provider if this becomes a real requirement."
        )

    def get_ohlc(self, instrument: str, timeframe: Timeframe, count: int) -> list[OHLCBar]:
        granularity = _TIMEFRAME_TO_GRANULARITY[timeframe]
        symbol = _to_oanda_symbol(instrument)
        resp = self._client.get(
            f"/v3/instruments/{symbol}/candles",
            params={"granularity": granularity, "count": count, "price": "M"},
        )
        resp.raise_for_status()
        bars = []
        for c in resp.json().get("candles", []):
            if not c.get("complete", True):
                continue
            mid = c["mid"]
            ts = dt.datetime.strptime(c["time"][:19], "%Y-%m-%dT%H:%M:%S").replace(
                tzinfo=dt.timezone.utc
            )
            bars.append(
                OHLCBar(
                    instrument=instrument,
                    timeframe=timeframe,
                    ts=ts,
                    open=Decimal(mid["o"]),
                    high=Decimal(mid["h"]),
                    low=Decimal(mid["l"]),
                    close=Decimal(mid["c"]),
                    volume=Decimal(str(c.get("volume", 0))),
                    provider=self.name,
                )
            )
        return bars

    def get_market_status(self, instrument: str) -> MarketStatus:
        # OANDA has no dedicated market-status endpoint for FX. FX trades
        # continuously Sun 22:00 UTC - Fri 22:00 UTC; use that as a heuristic
        # rather than claiming certainty the spec's data-quality checks don't
        # already give us (weekend anomalies are handled in the data-quality
        # layer, not invented here).
        now = dt.datetime.now(dt.timezone.utc)
        weekday = now.weekday()  # Mon=0 .. Sun=6
        if weekday == 5:  # Saturday
            return MarketStatus.CLOSED
        if weekday == 6 and now.hour < 22:  # Sunday before 22:00 UTC
            return MarketStatus.CLOSED
        if weekday == 4 and now.hour >= 22:  # Friday after 22:00 UTC
            return MarketStatus.CLOSED
        return MarketStatus.OPEN
