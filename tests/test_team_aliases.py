from bot.integrations import team_aliases


def test_resolve_returns_none_when_no_alias(conn):
    assert team_aliases.resolve(conn, "the-odds-api", "Texas Longhorns") is None


def test_add_alias_then_resolve(conn):
    team_aliases.add_alias(conn, "the-odds-api", "Texas Longhorns", "Texas")
    assert team_aliases.resolve(conn, "the-odds-api", "Texas Longhorns") == "Texas"


def test_add_alias_upserts_existing_mapping(conn):
    team_aliases.add_alias(conn, "the-odds-api", "Texas Longhorns", "Texas")
    team_aliases.add_alias(conn, "the-odds-api", "Texas Longhorns", "Texas Fixed")
    assert team_aliases.resolve(conn, "the-odds-api", "Texas Longhorns") == "Texas Fixed"


def test_resolve_is_scoped_by_source(conn):
    team_aliases.add_alias(conn, "the-odds-api", "Texas Longhorns", "Texas")
    assert team_aliases.resolve(conn, "some-other-source", "Texas Longhorns") is None
