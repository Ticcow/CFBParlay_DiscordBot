import os

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
os.environ.setdefault("CFBD_API_KEY", "test-cfbd-key")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")

import pytest

from bot.db import connect, run_migrations


@pytest.fixture
def conn():
    connection = connect(":memory:")
    run_migrations(connection)
    yield connection
    connection.close()
