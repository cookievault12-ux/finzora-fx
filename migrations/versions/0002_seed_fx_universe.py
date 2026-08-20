"""Seed FX universe + cross-asset instrument reference data.

Applied directly to Neon on 2026-08-19 alongside 0001. See that revision's
docstring for the stamp-vs-upgrade guidance — same applies here.

Revision ID: 0002_seed_fx_universe
Revises: 0001_initial_schema
Create Date: 2026-08-19
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0002_seed_fx_universe"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None

_SEED_SQL = Path(__file__).resolve().parents[1] / "sql" / "0002_seed_fx_universe.sql"


def upgrade() -> None:
    op.execute(_SEED_SQL.read_text())


def downgrade() -> None:
    op.execute("DELETE FROM instruments WHERE currency_pair_id IS NULL OR currency_pair_id IS NOT NULL;")
    op.execute("DELETE FROM currency_pairs;")
