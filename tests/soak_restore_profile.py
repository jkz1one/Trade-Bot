"""Optional timing of original restore digests in the isolated PAPER soak worker."""
import sys
import threading
import time
from collections import Counter
from datetime import datetime

from app.execution import restore


class OpeningRestoreProfile:
    def __init__(self, base, started):
        self.base = base
        self.started = started
        self.owner = threading.get_ident()
        self.original = restore._digest
        self.spans = []
        self.first_omitted = None
        self.lock = threading.Lock()

    def digest(self, db):
        if self.started[0] is None or self.first_omitted is not None:
            return self.original(db)
        frame = sys._getframe(1)
        while frame:
            module = frame.f_globals.get("__name__", "")
            if module.startswith("app.") and module not in ("app.execution.restore", "app.execution.journal"):
                break
            frame = frame.f_back
        caller = f"{module}.{frame.f_code.co_name}" if frame else "fixture"
        del frame
        start = time.monotonic()
        cpu = time.thread_time()
        try:
            return self.original(db)
        finally:
            end, used = time.monotonic(), time.thread_time() - cpu
            with self.lock:
                if len(self.spans) < 1024:
                    self.spans.append((start, end, used, threading.get_ident() == self.owner, caller))
                else:
                    self.first_omitted = min(start, self.first_omitted or start)

    def report(self, db, freshness):
        if freshness["status"] != "OBSERVED":
            return {"status": "UNMEASURED", "reason": "VERIFIED_OPENING_CLOCKS_REQUIRED"}
        # The finished worker and original session report verified every opening
        # in this disposable owner. Reuse the first reservation's approved quote.
        row = db.execute("""
            SELECT e.occurred_at, json_extract(o.approval_json,'$.inputs.quote.source_at'),
                   json_extract(o.approval_json,'$.inputs.quote.received_at')
            FROM execution_events e JOIN execution_portfolio_orders o USING(client_id)
            WHERE e.kind='PORTFOLIO_RESERVED' AND o.play_id=o.client_id AND e.occurred_at>=?
            ORDER BY e.sequence LIMIT 1
        """, (self.base.isoformat(),)).fetchone()
        if row is None:
            return {"status": "UNMEASURED", "reason": "OPENING_NOT_FOUND"}
        high, source, received = (self.started[0] + (datetime.fromisoformat(x) - self.base).total_seconds() for x in row)
        if source < self.started[0] or (self.first_omitted is not None and self.first_omitted < high):
            return {"status": "UNMEASURED", "reason": "OPENING_OUTSIDE_PROFILE"}
        return {"status": "OBSERVED", "reservation_at": row[0], "source_at": row[1], "received_at": row[2],
                "source_to_reservation": self.window(source, high), "receipt_to_reservation": self.window(received, high)}

    def window(self, low, high):
        merged = []
        callers = Counter()
        owner_cpu = other_cpu = 0.
        contained = 0
        for start, end, cpu, owner, caller in sorted(self.spans):
            if end <= low or start >= high:
                continue
            if low <= start and end <= high:
                contained += 1
                if owner:
                    owner_cpu += cpu
                    callers[caller] += 1
                else:
                    other_cpu += cpu
            start, end = max(start, low), min(end, high)
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return {"window_seconds": round(high - low, 6),
                "wall_seconds_with_digest_running": round(sum(end - start for start, end in merged), 6),
                "wholly_contained_calls": contained, "owner_thread_cpu_seconds": round(owner_cpu, 6),
                "background_cpu_seconds": round(other_cpu, 6), "owner_thread_calls": dict(callers)}
