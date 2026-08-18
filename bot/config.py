from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    discord_bot_token: str
    cfbd_api_key: str
    odds_api_key: str = ""
    database_path: str = "degen_bot.db"
    admin_log_channel_id: int | None = None
    dev_guild_id: int | None = None


settings = Settings()
