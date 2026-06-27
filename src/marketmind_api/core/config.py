from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_database_url() -> str:
    db_path = Path(__file__).resolve().parents[3] / '.data' / 'marketmind.db'
    return f"sqlite:///{db_path.as_posix()}"


class Settings(BaseSettings):
    app_env: str = 'development'
    api_host: str = '0.0.0.0'
    api_port: int = 8000
    database_url: str = ''
    redis_url: str = ''
    binance_rest_base_url: str = 'https://api.binance.com'
    binance_ws_base_url: str = 'wss://stream.binance.com:9443'
    binance_futures_ws_base_url: str = 'wss://fstream.binance.com'
    enable_binance_streams: bool = False
    market_monitor_timezone: str = 'Asia/Shanghai'
    market_monitor_run_at: str = '09:00,15:00,21:30,22:00'
    market_monitor_feishu_webhook_url: str = ''
    market_monitor_feishu_secret: str = ''
    market_api_key: str = ''
    binance_api_key: str = ''
    binance_api_secret: str = ''

    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')


settings = Settings()

if not settings.database_url:
    settings.database_url = _default_database_url()
