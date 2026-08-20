-- FINZORA FX — initial schema (Phase 1)
-- Applied directly to Neon via the Neon MCP tool on 2026-08-19 because this
-- sandbox has no outbound network access to run `alembic upgrade head`
-- directly (pip/psycopg egress is blocked here). The SQLAlchemy models in
-- src/database/models/ and the Alembic migration in
-- migrations/versions/0001_initial_schema.py mirror this file exactly.
-- On a machine with normal network access, run `alembic stamp head`
-- (NOT `upgrade head`) to mark this revision as already applied — running
-- upgrade would try to recreate tables that already exist on Neon.
--
-- All timestamps are TIMESTAMPTZ, stored in UTC. Application-layer
-- normalization to Asia/Singapore happens at the presentation layer only.

-- ============================================================
-- MARKET DATA
-- ============================================================

CREATE TABLE currency_pairs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol          TEXT NOT NULL UNIQUE,          -- e.g. 'EUR/USD'
    base_currency   TEXT NOT NULL,
    quote_currency  TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('MAJOR', 'CROSS')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE instruments (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol                  TEXT NOT NULL UNIQUE,
    asset_class             TEXT NOT NULL CHECK (asset_class IN
                                ('FX', 'COMMODITY', 'INDEX', 'BOND_YIELD', 'CREDIT_SPREAD', 'OTHER')),
    display_name            TEXT,
    is_tradeable            BOOLEAN NOT NULL DEFAULT FALSE,
    provider_instrument_ids JSONB NOT NULL DEFAULT '{}',  -- {"oanda": "EUR_USD", "fmp": "EURUSD"}
    currency_pair_id        BIGINT REFERENCES currency_pairs(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE price_data (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    timeframe       TEXT NOT NULL CHECK (timeframe IN ('1D', '4H', '1H', '15M', '5M')),
    ts              TIMESTAMPTZ NOT NULL,
    open            NUMERIC(18, 8),
    high            NUMERIC(18, 8),
    low             NUMERIC(18, 8),
    close           NUMERIC(18, 8),
    volume          NUMERIC(24, 4),
    bid             NUMERIC(18, 8),
    ask             NUMERIC(18, 8),
    spread          NUMERIC(18, 8),
    provider        TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, timeframe, ts, provider)
);
CREATE INDEX idx_price_data_lookup ON price_data (instrument_id, timeframe, ts DESC);

CREATE TABLE tick_data (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    ts              TIMESTAMPTZ NOT NULL,
    bid             NUMERIC(18, 8),
    ask             NUMERIC(18, 8),
    provider        TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tick_data_lookup ON tick_data (instrument_id, ts DESC);

CREATE TABLE market_features (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id       BIGINT NOT NULL REFERENCES instruments(id),
    timeframe           TEXT NOT NULL,
    ts                  TIMESTAMPTZ NOT NULL,
    feature_set_version TEXT NOT NULL,
    features            JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (instrument_id, timeframe, ts, feature_set_version)
);
CREATE INDEX idx_market_features_lookup ON market_features (instrument_id, timeframe, ts DESC);

CREATE TABLE cross_asset_data (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_symbol    TEXT NOT NULL,      -- 'GOLD','OIL_WTI','DXY','VIX','US10Y', etc.
    ts              TIMESTAMPTZ NOT NULL,
    value           NUMERIC(24, 8) NOT NULL,
    provider        TEXT NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (asset_symbol, ts, provider)
);
CREATE INDEX idx_cross_asset_lookup ON cross_asset_data (asset_symbol, ts DESC);

CREATE TABLE market_regimes (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL,
    regime_labels       JSONB NOT NULL,     -- e.g. ["TRENDING","HIGH_VOLATILITY","RISK_OFF"]
    confidence          NUMERIC(5, 4),
    methodology_version TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_market_regimes_ts ON market_regimes (ts DESC);

-- ============================================================
-- MACRO / CENTRAL BANK / GEOPOLITICAL INTELLIGENCE
-- ============================================================

CREATE TABLE macro_events (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_name      TEXT NOT NULL,
    country         TEXT NOT NULL,
    currency        TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    actual          NUMERIC(24, 8),
    forecast        NUMERIC(24, 8),
    previous        NUMERIC(24, 8),
    surprise        NUMERIC(24, 8),
    importance      TEXT CHECK (importance IN ('LOW', 'MEDIUM', 'HIGH')),
    source          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_macro_events_lookup ON macro_events (currency, ts DESC);

CREATE TABLE central_bank_events (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    central_bank            TEXT NOT NULL CHECK (central_bank IN
                                ('FED','ECB','BOE','BOJ','SNB','RBA','RBNZ','BOC','MAS')),
    event_type              TEXT NOT NULL CHECK (event_type IN
                                ('RATE_DECISION','MINUTES','SPEECH','MPS')),  -- MPS = MAS Monetary Policy Statement
    ts                      TIMESTAMPTZ NOT NULL,
    policy_rate             NUMERIC(8, 4),          -- null for MAS (band-based policy, not a rate)
    stance_score            NUMERIC(5, 4),          -- CentralBankStanceScore, -1 (dovish) to +1 (hawkish)
    forward_guidance_summary TEXT,
    source                  TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_central_bank_events_lookup ON central_bank_events (central_bank, ts DESC);

CREATE TABLE yield_data (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    country     TEXT NOT NULL,
    tenor       TEXT NOT NULL CHECK (tenor IN ('2Y', '5Y', '10Y')),
    ts          TIMESTAMPTZ NOT NULL,
    yield_value NUMERIC(8, 4) NOT NULL,
    source      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (country, tenor, ts, source)
);
CREATE INDEX idx_yield_data_lookup ON yield_data (country, tenor, ts DESC);

CREATE TABLE news_articles (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source              TEXT NOT NULL,
    source_tier         SMALLINT NOT NULL CHECK (source_tier BETWEEN 1 AND 4),
    title               TEXT NOT NULL,
    url                 TEXT,
    published_at        TIMESTAMPTZ NOT NULL,
    currencies_mentioned JSONB NOT NULL DEFAULT '[]',
    sentiment_score     NUMERIC(5, 4),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_news_articles_published ON news_articles (published_at DESC);

CREATE TABLE geopolitical_events (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type              TEXT NOT NULL,
    description              TEXT NOT NULL,
    countries_involved      JSONB NOT NULL DEFAULT '[]',
    currencies_affected     JSONB NOT NULL DEFAULT '[]',
    event_severity          NUMERIC(5, 4),
    currency_relevance      NUMERIC(5, 4),
    economic_relevance      NUMERIC(5, 4),
    historical_sensitivity  NUMERIC(5, 4),
    expected_duration_days  INTEGER,
    confidence              NUMERIC(5, 4),
    geopolitical_score      NUMERIC(5, 4),
    source_count            INTEGER NOT NULL DEFAULT 0,
    source_quality          NUMERIC(5, 4),
    ts                      TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_geopolitical_events_ts ON geopolitical_events (ts DESC);

-- ============================================================
-- STRATEGY / MODEL REGISTRY
-- ============================================================

CREATE TABLE strategies (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    family      TEXT NOT NULL CHECK (family IN
                    ('TREND_FOLLOWING','MEAN_REVERSION','BREAKOUT','MOMENTUM',
                     'CARRY','MACRO_DIVERGENCE','VOLATILITY_EXPANSION','EVENT_DRIVEN')),
    status      TEXT NOT NULL DEFAULT 'RESEARCH' CHECK (status IN
                    ('RESEARCH','BACKTEST','OUT_OF_SAMPLE','WALK_FORWARD','PAPER',
                     'VALIDATION','LIVE_PENDING_APPROVAL','LIVE','HALTED','DEGRADED')),
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE strategy_parameters (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id     BIGINT NOT NULL REFERENCES strategies(id),
    param_name      TEXT NOT NULL,
    param_value     JSONB NOT NULL,
    version         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE strategy_versions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id         BIGINT NOT NULL REFERENCES strategies(id),
    version_label       TEXT NOT NULL,      -- e.g. 'FINZORA-v0.1'
    parameters_snapshot JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (strategy_id, version_label)
);

CREATE TABLE model_versions (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_name  TEXT NOT NULL,      -- e.g. 'FINZORA-v0.1'
    component   TEXT NOT NULL,      -- e.g. 'signal_engine', 'regime_engine'
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (model_name, component)
);

-- ============================================================
-- SIGNALS (must be fully reproducible without querying live data)
-- ============================================================

CREATE TABLE signals (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts                      TIMESTAMPTZ NOT NULL,
    instrument_id           BIGINT NOT NULL REFERENCES instruments(id),
    direction               TEXT NOT NULL CHECK (direction IN ('LONG','SHORT','NO_TRADE')),
    entry_price             NUMERIC(18, 8),
    entry_range_low         NUMERIC(18, 8),
    entry_range_high        NUMERIC(18, 8),
    execution_method        TEXT CHECK (execution_method IN ('MARKET','LIMIT','STOP')),
    stop_loss               NUMERIC(18, 8),
    take_profit_1           NUMERIC(18, 8),
    take_profit_2           NUMERIC(18, 8),
    take_profit_3           NUMERIC(18, 8),
    risk_reward             NUMERIC(8, 4),
    technical_score         NUMERIC(5, 2),
    macro_score             NUMERIC(5, 2),
    geopolitical_score      NUMERIC(5, 2),
    cross_asset_score       NUMERIC(5, 2),
    regime_score            NUMERIC(5, 2),
    historical_setup_score  NUMERIC(5, 2),
    execution_score         NUMERIC(5, 2),
    risk_reward_score       NUMERIC(5, 2),
    composite_score         NUMERIC(5, 2),
    p_win                   NUMERIC(5, 4),
    p_loss                  NUMERIC(5, 4),
    expected_return         NUMERIC(8, 6),
    expected_loss           NUMERIC(8, 6),
    expected_value          NUMERIC(8, 6),
    expected_holding_period TEXT,           -- e.g. '3 days', '2 hours'
    sample_size             INTEGER,        -- historical setup matches used
    model_disagreement      BOOLEAN NOT NULL DEFAULT FALSE,
    strategy_id             BIGINT REFERENCES strategies(id),
    strategy_version_id     BIGINT REFERENCES strategy_versions(id),
    model_version_id        BIGINT REFERENCES model_versions(id),
    market_regime_id        BIGINT REFERENCES market_regimes(id),
    final_decision          TEXT NOT NULL CHECK (final_decision IN ('LONG','SHORT','NO_TRADE')),
    reason                  TEXT,
    llm_analysis            JSONB,          -- audit trail: provider, model, prompt version, output, confidence (no secrets)
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_signals_instrument_ts ON signals (instrument_id, ts DESC);

CREATE TABLE signal_features (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    signal_id       BIGINT NOT NULL REFERENCES signals(id),
    feature_name    TEXT NOT NULL,
    feature_value   NUMERIC(24, 10),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_signal_features_signal ON signal_features (signal_id);

-- ============================================================
-- PAPER TRADING
-- ============================================================

CREATE TABLE paper_orders (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    signal_id       BIGINT REFERENCES signals(id),
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    order_type      TEXT NOT NULL CHECK (order_type IN ('MARKET','LIMIT','STOP')),
    side            TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity        NUMERIC(18, 4) NOT NULL,
    price           NUMERIC(18, 8),
    status          TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN
                        ('PENDING','FILLED','PARTIALLY_FILLED','CANCELLED','REJECTED')),
    broker          TEXT NOT NULL DEFAULT 'PaperBroker',
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    filled_at       TIMESTAMPTZ
);

CREATE TABLE paper_trades (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    paper_order_id  BIGINT REFERENCES paper_orders(id),
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    direction       TEXT NOT NULL CHECK (direction IN ('LONG','SHORT')),
    entry_price     NUMERIC(18, 8) NOT NULL,
    exit_price      NUMERIC(18, 8),
    quantity        NUMERIC(18, 4) NOT NULL,
    stop_loss       NUMERIC(18, 8),
    take_profit     NUMERIC(18, 8),
    opened_at       TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ,
    pnl             NUMERIC(18, 4),
    pnl_pct         NUMERIC(8, 4),
    holding_period  INTERVAL,
    exit_reason     TEXT CHECK (exit_reason IN ('TP1','TP2','TP3','SL','TRAILING','MANUAL','TIMEOUT')),
    commission      NUMERIC(18, 4) NOT NULL DEFAULT 0,
    slippage        NUMERIC(18, 4) NOT NULL DEFAULT 0,
    financing_cost  NUMERIC(18, 4) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_paper_trades_instrument ON paper_trades (instrument_id, opened_at DESC);

CREATE TABLE positions (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    direction       TEXT NOT NULL CHECK (direction IN ('LONG','SHORT')),
    quantity        NUMERIC(18, 4) NOT NULL,
    avg_entry_price NUMERIC(18, 8) NOT NULL,
    unrealized_pnl  NUMERIC(18, 4),
    status          TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
    opened_at       TIMESTAMPTZ NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_positions_status ON positions (status);

CREATE TABLE portfolio_snapshots (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts                      TIMESTAMPTZ NOT NULL,
    equity                  NUMERIC(18, 4) NOT NULL,
    cash                    NUMERIC(18, 4) NOT NULL,
    unrealized_pnl          NUMERIC(18, 4) NOT NULL DEFAULT 0,
    realized_pnl            NUMERIC(18, 4) NOT NULL DEFAULT 0,
    drawdown_pct            NUMERIC(6, 4) NOT NULL DEFAULT 0,
    currency_exposure       JSONB NOT NULL DEFAULT '{}',   -- {"USD": 0.4, "EUR": -0.2, ...}
    open_positions_count    INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_portfolio_snapshots_ts ON portfolio_snapshots (ts DESC);

CREATE TABLE performance_metrics (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    period_start        TIMESTAMPTZ NOT NULL,
    period_end          TIMESTAMPTZ NOT NULL,
    period_type         TEXT NOT NULL CHECK (period_type IN ('DAILY','WEEKLY','MONTHLY','ALL_TIME')),
    cagr                NUMERIC(8, 4),
    sharpe              NUMERIC(8, 4),
    sortino             NUMERIC(8, 4),
    calmar              NUMERIC(8, 4),
    max_drawdown        NUMERIC(8, 4),
    win_rate            NUMERIC(6, 4),
    avg_win             NUMERIC(18, 4),
    avg_loss            NUMERIC(18, 4),
    profit_factor       NUMERIC(8, 4),
    expectancy          NUMERIC(18, 4),
    num_trades          INTEGER,
    turnover            NUMERIC(18, 4),
    transaction_costs   NUMERIC(18, 4),
    best_month          NUMERIC(8, 4),
    worst_month         NUMERIC(8, 4),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_performance_metrics_period ON performance_metrics (period_type, period_end DESC);

CREATE TABLE risk_events (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type              TEXT NOT NULL CHECK (event_type IN
                                ('CAUTION','REDUCE_RISK','RESTRICT_TRADING','HALT',
                                 'CONCENTRATION_BREACH','CORRELATION_BREACH','KILL_SWITCH')),
    ts                      TIMESTAMPTZ NOT NULL,
    details                 JSONB NOT NULL DEFAULT '{}',
    portfolio_snapshot_id   BIGINT REFERENCES portfolio_snapshots(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_risk_events_ts ON risk_events (ts DESC);

-- ============================================================
-- RESEARCH / VALIDATION
-- ============================================================

CREATE TABLE backtest_runs (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id             BIGINT NOT NULL REFERENCES strategies(id),
    strategy_version_id     BIGINT REFERENCES strategy_versions(id),
    instrument_id           BIGINT REFERENCES instruments(id),
    period_start            TIMESTAMPTZ NOT NULL,
    period_end              TIMESTAMPTZ NOT NULL,
    dataset_ref             TEXT,
    parameters              JSONB NOT NULL DEFAULT '{}',
    transaction_assumptions JSONB NOT NULL DEFAULT '{}',   -- spread, commission, slippage, financing, exec delay
    return_pct              NUMERIC(8, 4),
    cagr                    NUMERIC(8, 4),
    sharpe                  NUMERIC(8, 4),
    sortino                 NUMERIC(8, 4),
    max_drawdown            NUMERIC(8, 4),
    win_rate                NUMERIC(6, 4),
    profit_factor           NUMERIC(8, 4),
    expectancy              NUMERIC(18, 4),
    num_trades              INTEGER,
    costs                   NUMERIC(18, 4),
    best_trade              NUMERIC(18, 4),
    worst_trade             NUMERIC(18, 4),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_backtest_runs_strategy ON backtest_runs (strategy_id, created_at DESC);

CREATE TABLE walk_forward_runs (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id         BIGINT NOT NULL REFERENCES strategies(id),
    train_start         TIMESTAMPTZ NOT NULL,
    train_end           TIMESTAMPTZ NOT NULL,
    test_start          TIMESTAMPTZ NOT NULL,
    test_end            TIMESTAMPTZ NOT NULL,
    backtest_run_id     BIGINT REFERENCES backtest_runs(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_walk_forward_runs_strategy ON walk_forward_runs (strategy_id, created_at DESC);

CREATE TABLE monte_carlo_runs (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_id                 BIGINT NOT NULL REFERENCES strategies(id),
    based_on_backtest_run_id    BIGINT REFERENCES backtest_runs(id),
    num_simulations             INTEGER NOT NULL,
    probability_of_ruin         NUMERIC(6, 4),
    expected_drawdown           NUMERIC(8, 4),
    worst_case_drawdown         NUMERIC(8, 4),
    probability_return_gte_12   NUMERIC(6, 4),
    probability_return_gte_15   NUMERIC(6, 4),
    probability_drawdown_gt_20  NUMERIC(6, 4),
    probability_drawdown_gt_30  NUMERIC(6, 4),
    return_distribution         JSONB,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_monte_carlo_runs_strategy ON monte_carlo_runs (strategy_id, created_at DESC);

-- ============================================================
-- SYSTEM / DATA QUALITY
-- ============================================================

CREATE TABLE system_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type  TEXT NOT NULL CHECK (event_type IN
                    ('DATA_FAILURE','MODEL_FAILURE','BROKER_FAILURE','SYSTEM_FAILURE',
                     'TELEGRAM_FAILURE','SCHEDULER_FAILURE','RECOVERY')),
    severity    TEXT NOT NULL CHECK (severity IN ('INFO','WARNING','ERROR','CRITICAL')),
    component   TEXT NOT NULL,
    message     TEXT NOT NULL,
    details     JSONB NOT NULL DEFAULT '{}',
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX idx_system_events_ts ON system_events (ts DESC);

CREATE TABLE data_quality_events (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instrument_id           BIGINT REFERENCES instruments(id),
    issue_type              TEXT NOT NULL CHECK (issue_type IN
                                ('MISSING_CANDLE','DUPLICATE_CANDLE','TIMESTAMP_ERROR','STALE_PRICE',
                                 'ABNORMAL_SPIKE','ZERO_PRICE','NEGATIVE_PRICE','ABNORMAL_SPREAD',
                                 'PROVIDER_DISCREPANCY','WEEKEND_ANOMALY','TIMEZONE_ERROR')),
    timeframe               TEXT,
    ts                      TIMESTAMPTZ NOT NULL,
    details                 JSONB NOT NULL DEFAULT '{}',
    resulted_in_no_trade    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_data_quality_events_ts ON data_quality_events (ts DESC);
