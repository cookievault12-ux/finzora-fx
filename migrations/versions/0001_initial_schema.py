"""Initial FINZORA FX schema — 29 core tables + FX/cross-asset seed data.

This schema was applied directly to the Neon project "finzora-fx"
(project_id: orange-surf-82576014) via the Neon MCP tool on 2026-08-19,
because this build environment has no outbound network access to run
`alembic upgrade head` directly against Postgres.

On a machine with normal network access:
- If pointing at that SAME Neon database: run `alembic stamp head`
  (NOT `upgrade head`) — the tables already exist; stamp just records
  that this revision is applied, without re-running the DDL.
- If bootstrapping a FRESH database (e.g. local dev via docker-compose):
  run `alembic upgrade head` normally — this migration will execute the
  DDL below for the first time.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-19
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
_SCHEMA_SQL = _SQL_DIR / "0001_initial_schema.sql"

_DROP_ORDER = [
    "data_quality_events", "system_events", "monte_carlo_runs", "walk_forward_runs",
    "backtest_runs", "risk_events", "performance_metrics", "portfolio_snapshots",
    "positions", "paper_trades", "paper_orders", "signal_features", "signals",
    "model_versions", "strategy_versions", "strategy_parameters", "strategies",
    "geopolitical_events", "news_articles", "yield_data", "central_bank_events",
    "macro_events", "market_regimes", "cross_asset_data", "market_features",
    "tick_data", "price_data", "instruments", "currency_pairs",
]


def upgrade() -> None:
    op.execute(_SCHEMA_SQL.read_text())


def downgrade() -> None:
    for table in _DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
