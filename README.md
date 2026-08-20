# FINZORA FX

Institutional-style FX research, signal-generation, and paper-trading platform.
Base currency SGD, owner based in Singapore. Target benchmark: 12–15% annualized
return — an aspiration, not a guarantee. The correct decision is frequently
**NO TRADE**.

Live trading is disabled by default and requires explicit manual authorization.
No LLM and no automated model may enable live trading.

## Status

Phase 0 (research & architecture) complete — see `PHASE0_REPORT.md`.
Phase 1 (foundations: provider/broker interfaces, database, ingestion,
paper broker skeleton, Telegram hello-world, health endpoint) is in progress.

## Setup

1. Copy `.env.example` to `.env` and fill in real credentials. Never commit `.env`.
2. `pip install -e ".[dev]"`
3. For local dev database only: `docker compose --profile local-db up -d`
   (production uses Neon — see `DATABASE_URL` in `.env`).
4. Run tests: `pytest`

## Project layout

- `config/` — settings, risk parameters, instrument universe, provider config, strategy registry
- `src/` — application code, one package per architectural layer (data, providers, brokers, market, features, macro, central_banks, geopolitical, news, regimes, strategies, signals, risk, portfolio, backtesting, paper_trading, llm, telegram, dashboard, monitoring, database, api)
- `tests/` — unit + integration tests
- `migrations/` — Alembic database migrations
- `notebooks/` — research notebooks (not production code)
- `scripts/` — one-off/maintenance scripts

## Design principles

1. Capital preservation before data quality before statistical validity before
   risk management before positive expected value before consistency before
   the return target. Never reversed.
2. Every provider and broker is swappable via `config/providers.yaml` —
   never hardcoded.
3. The Risk layer can never be bypassed by any LLM or automated model.
4. No performance figure is ever reported unless it comes from an actual
   recorded experiment.
