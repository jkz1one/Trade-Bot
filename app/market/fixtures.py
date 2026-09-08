from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.domain.models import Candidate, Quote
from app.market.base import UniverseProvider


class FixtureMarketProvider(UniverseProvider):
    def candidates(self) -> list[Candidate]:
        now = datetime.now(timezone.utc)
        raw = [
            ("SPY", "648.10", "648.14", "648.12", "0.011", "0.008", "0.004"),
            ("QQQ", "575.20", "575.24", "575.22", "0.014", "0.011", "0.008"),
            ("AAPL", "232.10", "232.14", "232.12", "0.018", "0.015", "0.006"),
        ]
        return [
            Candidate(
                quote=Quote(symbol=s, timestamp=now, bid=Decimal(b), ask=Decimal(a), last=Decimal(l), fractional_tradable=True),
                atr_fraction=Decimal(atr), realized_vol_fraction=Decimal(rv), day_change_fraction=Decimal(chg),
                above_vwap=True, relative_volume=Decimal("1.2"),
            )
            for s, b, a, l, atr, rv, chg in raw
        ]
