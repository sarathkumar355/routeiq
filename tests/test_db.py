"""
Basic database connectivity test.

Skipped automatically if DATABASE_URL isn't configured, since Postgres is
optional in Phase 1 — this test exists so that *when* you do configure a
local database, you have an immediate way to confirm the connection layer
works before building anything on top of it.
"""

import pytest

from app.config import get_settings
from app.db.session import check_database_connection

settings = get_settings()


@pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL not configured — skipping DB connectivity test",
)
def test_database_connection():
    assert check_database_connection() is True
