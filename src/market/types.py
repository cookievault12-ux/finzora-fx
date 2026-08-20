"""Shared market data value objects.

Used by both `src/providers` (MarketDataProvider implementations) and
`src/brokers` (BrokerAdapter implementations) so the two layers agree on
shape without importing from each other.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Timeframe(str, Enum):
    D1 = "1D"
    H4 = "4H"
    H1 = "1H"
    M15 = "15M"
    M5 = "5M"


@dataclass(frozen=True, slots=True)
class InstrumentInfo:
    symbol: str  # e.g. 'EUR/USD'
    asset_class: str  # 'FX' | 'COMMODITY' | 'INDEX' | 'BOND_YIELD' | 'CREDIT_SPREAD' | 'OTHER'
    is_tradeable: bool
    provider_instrument_id: str  # provider's own symbol, e.g. 'EUR_USD' for OANDA


@dataclass(frozen=True, slots=True)
class OHLCBar:
    instrument: str
    timeframe: Timeframe
    ts: dt.datetime  # UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    provider: str


@dataclass(frozen=True, slots=True)
class Quote:
    instrument: str
    ts: dt.datetime  # UTC
    bid: Decimal
    ask: Decimal
    provider: str

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def mid(self) -> Decimal:
        return (self.ask + self.bid) / 2


@dataclass(frozen=True, slots=True)
class Tick:
    instrument: str
    ts: dt.datetime  # UTC
    bid: Decimal
    ask: Decimal
    provider: str


class MarketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"
