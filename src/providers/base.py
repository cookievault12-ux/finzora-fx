"""MarketDataProvider interface (spec section 11).

Every data provider (OANDA, Alpha Vantage, FMP, Twelve Data, ...) implements
this so the rest of the system never depends on a specific vendor. Providers
are selected via config/providers.yaml, never hardcoded into application logic.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

from src.market.types import InstrumentInfo, MarketStatus, OHLCBar, Quote, Tick, Timeframe


class MarketDataProvider(ABC):
    """Abstract base for all market-data vendors."""

    name: str  # e.g. 'oanda', 'alpha_vantage', 'fmp'

    @abstractmethod
    def get_instruments(self) -> list[InstrumentInfo]:
        """Return the instruments this provider can serve."""

    @abstractmethod
    def get_historical_prices(
        self,
        instrument: str,
        timeframe: Timeframe,
        start: dt.datetime,
        end: dt.datetime,
    ) -> list[OHLCBar]:
        """Return OHLC bars for [start, end), both UTC, inclusive of start."""

    @abstractmethod
    def get_realtime_prices(self, instruments: list[str]) -> list[Quote]:
        """Return the latest quote for each requested instrument."""

    @abstractmethod
    def get_bid_ask(self, instrument: str) -> Quote:
        """Return the current bid/ask for a single instrument."""

    @abstractmethod
    def get_spreads(self, instruments: list[str]) -> dict[str, float]:
        """Return current spread (ask - bid) per instrument, as float pips/points."""

    @abstractmethod
    def get_ticks(self, instrument: str, start: dt.datetime, end: dt.datetime) -> list[Tick]:
        """Return tick data if the provider supports it. Raise NotImplementedError otherwise."""

    @abstractmethod
    def get_ohlc(
        self, instrument: str, timeframe: Timeframe, count: int
    ) -> list[OHLCBar]:
        """Return the most recent `count` OHLC bars (convenience over get_historical_prices)."""

    @abstractmethod
    def get_market_status(self, instrument: str) -> MarketStatus:
        """Return whether the instrument's market is currently open."""
