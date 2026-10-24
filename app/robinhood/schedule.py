from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.models import utc_now
from app.storage.repository import Repository


@dataclass(frozen=True)
class SessionWindow:
    session_date: str
    opens_at: datetime
    closes_at: datetime
    scheduled_for: datetime

    @property
    def key(self) -> str:
        return "SHADOW:XNYS:" + self.scheduled_for.astimezone(timezone.utc).isoformat()

    def is_open(self, now: datetime) -> bool:
        return self.opens_at <= now < self.closes_at

    def context(self) -> dict[str, str]:
        return {
            "calendar": "XNYS", "session_date": self.session_date,
            "regular_open": self.opens_at.isoformat(),
            "regular_close": self.closes_at.isoformat(),
            "scheduled_for": self.scheduled_for.isoformat(),
        }


class XNYSCalendar:
    """Local exchange calendar, with holidays, DST and early closes; no network calls."""

    def __init__(self):
        import exchange_calendars

        self.calendar = exchange_calendars.get_calendar("XNYS")

    def current_window(self, now: datetime) -> SessionWindow | None:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Scheduler clock must be timezone-aware")
        day = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if not self.calendar.is_session(day):
            return None
        opens = self.calendar.session_open(day).to_pydatetime()
        closes = self.calendar.session_close(day).to_pydatetime()
        if not opens <= now < closes:
            return None
        # Fixed 15-minute cadence anchored to the actual session open.
        slot = int((now - opens).total_seconds() // 900)
        return SessionWindow(day, opens, closes, opens + timedelta(minutes=15 * slot))


class ShadowScheduler:
    def __init__(
        self, repo: Repository, run_cycle: Callable[[SessionWindow, str], Awaitable[int]],
        *, calendar=None, clock: Callable[[], datetime] = utc_now,
    ):
        self.repo = repo
        self.run_cycle = run_cycle
        self.calendar = calendar if calendar is not None else XNYSCalendar()
        self.clock = clock

    async def tick(self) -> dict:
        try:
            now = self.clock()
            window = self.calendar.current_window(now)
        except Exception as exc:
            return {"status": "ERROR", "reason": "CALENDAR_FAILURE",
                    "error_class": type(exc).__name__, "exit_code": 12}
        if window is None:
            return {"status": "SKIPPED", "reason": "MARKET_CLOSED", "exit_code": 0}
        token = uuid4().hex
        if not self.repo.claim_shadow_slot(window, token, now):
            existing = self.repo.shadow_slot(window.key)
            active = self.repo.active_shadow_slot()
            if active is not None:
                return {"status": "BLOCKED", "reason": "RUN_IN_PROGRESS",
                        "slot_key": active.slot_key, "exit_code": 10}
            return {"status": "SKIPPED", "reason": "SLOT_ALREADY_ATTEMPTED",
                    "slot_key": window.key, "cycle_id": existing.cycle_id if existing else None,
                    "exit_code": existing.exit_code if existing else 10}
        try:
            code = await self.run_cycle(window, token)
            row = self.repo.shadow_slot(window.key)
            if row is None or row.status == "CLAIMED":
                # Preflight failures or an unexpectedly missing cycle cannot count as success.
                code = code or 11
                self.repo.fail_shadow_slot(window.key, token, code, "CycleNotPersisted")
            elif row.exit_code != code:
                code = 11
        except Exception as exc:
            code = 11
            self.repo.fail_shadow_slot(window.key, token, code, type(exc).__name__)
        row = self.repo.shadow_slot(window.key)
        return {
            "status": "COMPLETED" if code == 0 else "ERROR", "exit_code": code,
            "slot_key": window.key, "cycle_id": row.cycle_id if row else None,
            "error_class": row.error_class if row else None,
        }
