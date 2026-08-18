from bot.config import Settings


def test_blank_optional_ids_are_treated_as_none():
    settings = Settings(
        discord_bot_token="x",
        cfbd_api_key="y",
        admin_log_channel_id="",
        dev_guild_id="",
    )
    assert settings.admin_log_channel_id is None
    assert settings.dev_guild_id is None


def test_numeric_optional_ids_still_parse():
    settings = Settings(
        discord_bot_token="x",
        cfbd_api_key="y",
        admin_log_channel_id="12345",
        dev_guild_id="67890",
    )
    assert settings.admin_log_channel_id == 12345
    assert settings.dev_guild_id == 67890


def test_unset_optional_ids_default_to_none():
    settings = Settings(discord_bot_token="x", cfbd_api_key="y")
    assert settings.admin_log_channel_id is None
    assert settings.dev_guild_id is None
