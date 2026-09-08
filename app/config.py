from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRADER_", env_file=".env", extra="ignore")

    mode: str = "PAPER"
    starting_capital: Decimal = Decimal("10.00")
    db_url: str = "sqlite:///./trader.db"
    live_enabled: bool = False
    model_name: str = "gpt-5.6-luna"
    model_input_usd_per_million: Decimal = Decimal("0.20")
    model_output_usd_per_million: Decimal = Decimal("1.20")
    benchmark_symbol: str = "SPY"
    min_order_notional: Decimal = Decimal("1.00")
    quote_max_age_seconds: int = 90
    max_daily_entries: int = 8
    exit_cooldown_minutes: int = 15
    initial_symbols: list[str] = Field(
        default_factory=lambda: [
            "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLI", "XLV", "XLY",
            "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "JPM", "COST",
        ]
    )

    @property
    def normalized_mode(self) -> str:
        return self.mode.upper()


@lru_cache
def get_settings() -> Settings:
    return Settings()
