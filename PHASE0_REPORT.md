# FINZORA FX — PHASE 0 REPORT

*Research date: 18 August 2026. This is a research and architecture deliverable — no code has been written. Per the project specification, this stops here for owner review and approval before Phase 1 implementation begins.*

---

## 1. Executive Summary

FINZORA FX is an institutional-style FX research, signal-generation, and paper-trading platform for a Singapore-based owner, targeting a 12–15% annualized return benchmark (not a guarantee) with strict capital-preservation discipline — the system is designed to say **NO TRADE** whenever the evidence doesn't support one.

Phase 0 research confirms the project is buildable with a lean, mostly-free-to-low-cost provider stack, using the connectors already wired into this workspace (Alpha Vantage, FMP, Neon, Railway, Exa) plus a small number of free additions (FRED, GDELT, central bank RSS feeds). The one real gap in the current stack is **deep intraday FX history and true streaming quotes** — Alpha Vantage and FMP alone cannot supply 5–10 years of 5M/15M/1H/4H FX bars. A single supplementary provider (Twelve Data or Polygon.io) closes this.

For execution, **OANDA Asia Pacific Pte. Ltd.** is the recommended primary broker for the paper-trading phase — it holds an active MAS Capital Markets Services Licence (verified today against MAS's Financial Institutions Directory), offers the deepest FX-specific intraday history and a frictionless practice/demo API, and has the simplest integration path. Saxo and Interactive Brokers Singapore are documented as strong alternates, particularly IBKR for eventual live execution quality.

Nothing here is a live-trading recommendation. Live trading remains disabled by design (`live_trading_enabled: false`) until the owner explicitly authorizes it after paper-trading graduation.

---

## 2. Recommended Architecture

Layered per the project's own design principle — Research → Intelligence → Signal → Risk → Execution — with the Risk layer never bypassable by any LLM:

```
GLOBAL MARKET DATA (FX prices, macro, cross-asset)
        │
FEATURE ENGINEERING → MARKET REGIME ENGINE
        │
   ┌────┴─────┐
   ▼          ▼
QUANT ENGINE   NEWS/GEOPOLITICAL → LLM ANALYSIS (Claude + Nemotron)
   │          │
   └────┬─────┘
        ▼
   SIGNAL ENGINE
        ▼
    RISK ENGINE  ← never bypassed by any LLM
        ▼
 PORTFOLIO DECISION
   ┌────┴─────┐
   ▼          ▼
PAPER TRADE   NO TRADE
   │
   ▼
TELEGRAM → PERFORMANCE DB → STRATEGY VALIDATION → LIVE ELIGIBILITY → MANUAL APPROVAL ONLY → LIVE EXECUTION
```

Each layer is a separate Python package under `src/` per the project structure the owner specified (section 81 of the spec), communicating through well-defined interfaces (`MarketDataProvider`, `BrokerAdapter`) so providers and brokers are swappable via configuration, never hardcoded.

---

## 3. Broker Comparison

Full detail, MAS verification, and sourcing in the standalone broker research; summarized here.

| Broker | Singapore entity | MAS status (verified 18 Aug 2026) | API | Demo | Score |
|---|---|---|---|---|---|
| **OANDA** | OANDA Asia Pacific Pte. Ltd. | Active CMSL + Exempt Financial Adviser | REST v20 + streaming pricing, 5-second candles up, best FX-specific intraday depth | Fully separate practice API, no live linkage | **8.5/10** |
| **Saxo** | Saxo Capital Markets Pte. Ltd. | Active CMSL, explicit leveraged spot-FX authorisation | OpenAPI (REST + WebSocket), multi-asset | Free demo/SIM, separate demo OpenAPI env | 8/10 |
| **Interactive Brokers** | Interactive Brokers Singapore Pte. Ltd. | Active CMSL, broadest mandate incl. explicit leveraged spot-FX | TWS API/Gateway (socket-based), `ib_insync` | Paper account, $1M virtual funds, same API as live | 7.5/10 |
| **IG** | IG Asia Pte Ltd | Active CMSL (OTC-derivatives category) | REST + Lightstreamer, 40-subscription streaming cap | Demo requires linking to a live-account email | 6.5/10 |
| ~~FXCM~~ | — | **Not MAS-licensed; does not accept Singapore residents** | — | — | Excluded |
| ~~City Index SG~~ | — | Brand discontinued Apr 2025, migrated to FOREX.com/StoneX | — | — | Superseded |

**PRIMARY_EXECUTION_PROVIDER: OANDA** (config value, not hardcoded). **Fallback/live-upgrade path: Interactive Brokers Singapore**, whose paper→live parity aligns cleanly with the "manual authorization only" live-trading gate.

---

## 4. Market Data Comparison

Alpha Vantage and FMP (already connected) cover FX daily/weekly/monthly bars, commodities, US macro/yields, and most cross-asset indices — but **neither can deliver 5–10 years of intraday (5M/15M/1H/4H) FX history**, and neither offers true FX streaming/bulk bid-ask (Alpha Vantage's bulk quote endpoints are equities-only; its FX intraday endpoint is hard-capped at ~30 days regardless of paid tier).

| Gap | Fix |
|---|---|
| Deep intraday FX history + streaming | **Twelve Data** (20+ yr history, 1min–1month intervals, WebSocket on Pro) or **Polygon.io** (native Forex WebSocket + tick quotes, higher cost) |
| Free one-time historical backfill seed | **Dukascopy** (tick/bar export) or **TrueFX** (free tick feed, ~15 major pairs) |
| International daily sovereign yields (DE/UK/JP/AU/CA), credit spreads, commodity indices | Accepted gap for v1 — FRED's international series are monthly/quarterly only; revisit with a commercial aggregator later if needed |

**PRIMARY_DATA_PROVIDER: FMP** (Premium tier) · **BACKUP_DATA_PROVIDER: Alpha Vantage** (existing) · **SUPPLEMENTARY_PROVIDER: Twelve Data** (intraday FX + streaming gap-filler). All three as swappable config, since FMP's WebSocket/1-min tier gating and Alpha Vantage's intraday ceiling both need direct verification against live keys before final commitment.

---

## 5. News / Macro / Geopolitical Data Comparison

FMP's economic calendar is the workhorse for multi-central-bank (Fed, ECB, BOE, BOJ, SNB, RBA, RBNZ, BOC) actual/forecast/previous data; Alpha Vantage's macro tools are US-only supplements. Neither ingests verbatim primary-source text, and neither models MAS's actual policy tool (a S$NEER band via semi-annual Monetary Policy Statement, not a policy rate) — MAS needs direct monitoring of its own press releases rather than a generic calendar row.

Recommended free additions:
- **FRED** — deep historical US macro/rate series, free, 120 req/min.
- **GDELT** — structured, CAMEO-coded geopolitical event stream (actor/target/type/tone/Goldstein scale) updated every 15 minutes, free, no API key — closes the "structured geopolitical event" gap that Exa's unstructured search can't fill alone.
- **Central bank RSS/press-release feeds** (Fed, ECB, BOE, BOJ, SNB, RBA, RBNZ, BOC, MAS) pulled directly — the actual Tier 1 "official release" source, verbatim and lowest-latency.

Explicitly **not** recommended (paid, low value relative to free stack): Trading Economics API, NewsAPI.org. **Open gap, no fix exists**: structured rate-expectation/forward-guidance data (e.g., CME FedWatch has no public API) — document this honestly rather than approximate it.

---

## 6. Singapore Regulatory Considerations

- Verified today against MAS's Financial Institutions Directory (eservices.mas.gov.sg/fid): OANDA, Saxo, IBKR Singapore, and IG Asia all hold active Capital Markets Services Licences.
- IG and OANDA are licensed under the *OTC Derivatives Contracts* category; Saxo and IBKR additionally carry the explicit *"Spot Foreign Exchange Contracts for the Purposes of Leveraged Foreign Exchange Trading"* line item. This is a real MAS categorization distinction worth documenting in FINZORA's own compliance records, not a disqualifier for IG/OANDA.
- FXCM is confirmed **not** MAS-licensed and does not accept Singapore residents — excluded entirely.
- This verification has a timestamp (18 Aug 2026) and must be re-checked immediately before any live (non-paper) capital commitment, since licences and terms change.

---

## 7. Recommended Provider Stack

| Category | Primary | Backup / Supplementary |
|---|---|---|
| Execution broker | OANDA Asia Pacific | Interactive Brokers Singapore (live-upgrade path) |
| Market data | FMP | Alpha Vantage (backup) + Twelve Data (intraday/streaming gap-filler) |
| Historical backfill seed | Dukascopy / TrueFX (free, one-time) | — |
| Macro / economic calendar | FMP economic calendar | FRED (US depth), central bank RSS (Tier 1 primary source) |
| Geopolitical | Exa (unstructured search) | GDELT (structured event stream) |
| Database | Neon (Postgres) | — |
| Hosting | Railway | — |
| Primary LLM | Anthropic Claude | — |
| Secondary LLM | NVIDIA Nemotron 3 | — |
| Notifications | Telegram Bot API | — |

---

## 8. Cost Estimate

*Estimates only — verify exact tier pricing before committing; all figures in USD/month unless noted.*

| Configuration | Market data | Database/Hosting | LLM (variable, usage-based) | Est. total/mo |
|---|---|---|---|---|
| **Minimum-cost** | Free tiers (AV free, FMP free, Exa free, FRED/GDELT free) + Dukascopy one-time backfill + OANDA demo (free) | Neon free tier + Railway free/hobby (~$5) | Claude API light usage (~$20–40) + Nemotron via free/low-cost tier | **~$25–50** |
| **Recommended** | FMP Premium (~$59) + Alpha Vantage Premium (~$50) + Twelve Data Grow (~$79) | Neon paid (~$19–69) + Railway (~$20–50) | Claude + Nemotron moderate usage (~$100–200) | **~$330–500** |
| **Professional** | Add Polygon.io Forex tier (~$199+) in place of/alongside Twelve Data, EODHD All-in-One (~$100) for redundancy | Dedicated Postgres + higher-tier hosting (~$150–300) | Higher-volume LLM usage, both models (~$300–600) | **~$800–1,400+** |

Broker execution itself (OANDA/Saxo/IBKR) carries no separate data fee while paper trading — cost is embedded in spread/commission once live.

---

## 9. Database Schema

PostgreSQL (Neon), core tables per the owner's specification (section 62): `currency_pairs`, `instruments`, `price_data`, `tick_data`, `market_features`, `macro_events`, `central_bank_events`, `yield_data`, `cross_asset_data`, `news_articles`, `geopolitical_events`, `market_regimes`, `strategies`, `strategy_parameters`, `signals`, `signal_features`, `paper_orders`, `paper_trades`, `positions`, `portfolio_snapshots`, `performance_metrics`, `risk_events`, `model_versions`, `strategy_versions`, `backtest_runs`, `walk_forward_runs`, `monte_carlo_runs`, `system_events`, `data_quality_events`.

Detailed column-level DDL is a Phase 1 deliverable (needs the finalized provider schemas to map fields correctly) — Phase 0 confirms the table list and that every signal-reproducibility requirement (section 63) is satisfiable: each signal row will FK into the exact features, macro state, geopolitical state, regime, strategy version, model version, and risk parameters used, so historical signals reconstruct without querying live data.

---

## 10. System Architecture Diagram

See Section 2 above — the layered pipeline is the authoritative diagram. Provider/broker abstraction sits beneath the Market Data and Execution boxes respectively, via the `MarketDataProvider` and `BrokerAdapter` interfaces the owner specified.

---

## 11. LLM Architecture

- **Claude (primary)**: architecture, coding, debugging, research, orchestration, documentation. Drives Claude Code as the primary development agent.
- **Nemotron 3 (secondary)**: independent news/geopolitical/macro analysis, second-opinion review, contradiction detection. Runs as an isolated analytical component — never a vote-caster on buy/sell.
- Both models are tool-restricted (Section 67 tools only: `get_market_data`, `get_historical_data`, `get_macro_events`, `get_news`, `get_geopolitical_events`, `get_current_regime`, `run_backtest`, `get_portfolio`, `calculate_position_size`, `validate_signal`, `send_telegram`) — no shell, no DB credentials, no broker secrets, no Telegram token, no live-trading credentials.
- On disagreement: `MODEL_DISAGREEMENT = TRUE` → NO TRADE or confidence reduction per a configurable policy. AI consensus is never treated as statistical evidence.

---

## 12. Risk Architecture

Risk defaults per the owner's configuration, reinterpreting "30%" correctly as the ceiling on eventual live capital allocation, never per-trade risk:

```yaml
risk:
  risk_per_trade: { default: 0.005, maximum: 0.0075 }
  maximum_total_open_risk: 0.02
  maximum_portfolio_drawdown: 0.30
  soft_drawdown_limit: 0.15
  emergency_drawdown_limit: 0.25
```

Drawdown schedule: 15% → CAUTION, 20% → reduce risk, 25% → strongly restrict, 30% → halt. Portfolio risk is tracked by net currency exposure (not per-pair), with correlation/concentration checks rejecting new positions that add excessive factor exposure. The Risk Engine sits structurally between Signal and Portfolio Decision and cannot be bypassed by any LLM or automated model — this is enforced in code, not by prompt instruction.

---

## 13. Paper Trading Architecture

`PaperBroker` implements the same `BrokerAdapter` interface live brokers will later use, simulating market/limit/stop orders, TP1/TP2/trailing stops, position sizing, margin, financing, spread, slippage, and partial fills — starting capital SGD 10,000. Because OANDA's practice API mirrors its live API 1:1, FINZORA can optionally validate `PaperBroker` fills against OANDA practice-account fills as a realism check without any live-capital exposure.

---

## 14. Telegram Architecture

Bot posts to the "Finzora" channel using `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — never hardcoded, never logged, never sent to any LLM. Alert types per spec section 59 (`NEW_SIGNAL` through `NO_TRADE`), with the no-trade market scan and daily/weekly reports treated as first-class features, not afterthoughts — the system should be comfortable telling the owner "NO TRADE" for days at a stretch.

---

## 15. Security Architecture

- Secrets (Telegram token, broker keys, DB credentials, LLM API keys) live in environment variables only, per `.env.example` — never committed, never printed, never passed to an LLM.
- LLM tool access is allowlisted (Section 67) — no shell, no direct DB access, no live-trading credentials reachable by any model.
- Kill switch (stop new orders, cancel pending, optionally close positions, disable live trading) is implemented independent of any LLM.
- `GET /health` reports on database, market data, macro data, news, LLM, Telegram, broker, and scheduler status.

---

## 16. Development Roadmap

- **Phase 1 — Foundations**: provider/broker adapter interfaces, `PaperBroker`, database schema + migrations (Neon), scheduled data ingestion (Alpha Vantage/FMP/Twelve Data), data-quality checks, Telegram bot skeleton, health endpoint. *Deliverable: data flowing end-to-end into Postgres with quality checks, and a Telegram "hello world" post.*
- **Phase 2 — Feature & Regime Engines**: trend/momentum/volatility/statistical/price-structure features; market regime classification. *Deliverable: reproducible feature store with incremental-value testing.*
- **Phase 3 — Macro & Geopolitical Intelligence**: FMP economic calendar + FRED + central bank RSS ingestion, GDELT event stream, Nemotron-driven geopolitical scoring with defined methodology (not LLM-invented numbers). *Deliverable: `CentralBankStanceScore` and `geopolitical_score` populated historically.*
- **Phase 4 — Signal Engine & Backtesting**: multi-factor signal scoring, expected-value gating, historical setup matching with sample-size protection, professional backtester (no look-ahead/leakage), walk-forward framework. *Deliverable: first honestly-reported backtest results — no fabricated figures.*
- **Phase 5 — Risk, Portfolio, Paper Trading**: risk engine, currency-exposure/correlation control, drawdown schedule, full `PaperBroker` simulation, Telegram signal/report formats. *Deliverable: live paper trading against OANDA practice-mirrored assumptions.*
- **Phase 6 — Validation**: Monte Carlo, stress testing, out-of-sample freeze, Live Readiness Report. *Deliverable: the report itself — not a live-trading decision, which remains the owner's alone.*

---

## 17. Required API Accounts

Already connected: Alpha Vantage, FMP, Neon, Railway, Exa. Still needed: OANDA (demo account + API token — free), Twelve Data (account + API key), Anthropic API key, NVIDIA Nemotron API key, Telegram bot token (via @BotFather) + Finzora channel chat ID. All to be added to `.env` per the variable list in spec section 83 — never committed.

---

## 18. Risks and Limitations

- Every regulatory and pricing figure in this report is timestamped 18 Aug 2026 and must be re-verified before any live-capital decision — MAS licences, broker spreads, and API pricing all change.
- Free-tier data (Alpha Vantage, FMP free) will not sustain the full 20-pair × 5-timeframe backfill without hitting throttling; budget for at least entry-level paid tiers before Phase 1 ingestion.
- No provider in the current stack supplies structured rate-expectation/forward-guidance data — this is an accepted open gap, not a solved problem.
- International daily sovereign bond yields and commodity indices remain a lower-priority gap for v1.
- All performance figures throughout the system's life must come from actual recorded experiments — this report contains no invented backtest results, and none should ever be presented as such.

---

## 19. Open Decisions (for the owner)

1. Confirm OANDA as primary broker, or prefer Saxo/IBKR given their broader MAS mandate despite more integration overhead.
2. Approve budget tier (minimum/recommended/professional) for the data-provider stack — this determines whether Twelve Data or Polygon.io is used for the intraday-FX gap.
3. NVIDIA Nemotron 3 access path (hosted API vs. self-hosted deployment) — not yet researched in this pass; needed before Phase 3.
4. Hosting posture on Railway — confirm acceptable for scheduled jobs + FastAPI + Postgres connection pooling at the chosen tier, or evaluate alternatives.

---

## 20. Proposed Phase 1

Scope: provider/broker abstraction interfaces, database schema + migrations, scheduled ingestion for FX daily/intraday + macro calendar, data-quality validation pipeline, `PaperBroker` skeleton, Telegram "hello world," `/health` endpoint. No signal generation, no LLM analysis, no trading logic yet — foundations only, with tests for data ingestion and the paper broker per spec section 96.

**Awaiting owner review and approval before any implementation begins.**
