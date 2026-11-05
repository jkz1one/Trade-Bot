"""One reviewed, quota-charged collection after a settled Scope decision.

The collector remains the sole feed writer. Only completed native delivery can
return to the paid decision; this handoff grants no admission or order authority.
"""
import asyncio
import json
from datetime import datetime

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint


class ScopeRefreshUnavailable(ExecutionBlocked):
    """A bounded read could not provide timely evidence; retain the paid HOLD."""


def enabled(binding):
    return binding is not None and binding.post_cost_refresh == 'bounded-paid-refresh-v1'


def validate_ticket(feed, ticket, now):
    from zoneinfo import ZoneInfo

    binding = feed.policy_for(now.astimezone(ZoneInfo('America/New_York')).date()).scope_binding
    row = feed.db.execute(
        'SELECT payload_hash,status FROM scope_refresh_requests WHERE cycle_key=?',
        (ticket['cycle_key'],)).fetchone()
    if (not enabled(binding) or fingerprint(binding) != ticket['binding_sha256']
            or binding.play_key() != ticket['play_key']
            or not binding.session.opens_at <= now < binding.session.closes_at
            or not datetime.fromisoformat(ticket['requested_at']) <= now
            < datetime.fromisoformat(ticket['valid_until'])
            or row is None or row['status'] != 'QUEUED'
            or row['payload_hash'] != fingerprint(ticket)):
        raise ExecutionBlocked('SCOPE_PAID_REFRESH_NOT_CURRENT')


class ConnectedScopeRefresh:
    def __init__(self, runtime, feed, stop):
        self.runtime, self.feed, self.stop = runtime, feed, stop
        self.wake = asyncio.Event()
        self.pending = None
        feed.db.execute('''CREATE TABLE IF NOT EXISTS scope_refresh_requests(
            cycle_key TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,
            status TEXT NOT NULL,capture_sequence INTEGER,result_json TEXT)''')
        # A restarted process cannot replay a paid request or its collector read.
        feed.db.execute("UPDATE scope_refresh_requests SET status='INTERRUPTED' "
                        "WHERE status IN ('QUEUED','CAPTURING')")
        feed.db.commit()

    async def fresh(self, play_key):
        from zoneinfo import ZoneInfo
        from app.options.scope_ai import validate_stored

        r, feed = self.runtime, self.feed
        if self.stop.is_set() or self.pending is not None:
            raise ExecutionBlocked('SCOPE_PAID_REFRESH_UNAVAILABLE')
        # Enforce native completion/protection and entry-halt checks first.
        await r.scope.fresh(play_key)
        now = r.c.now()
        binding = feed.policy_for(now.astimezone(ZoneInfo('America/New_York')).date()).scope_binding
        if not enabled(binding):
            return await r.scope.fresh(play_key)
        if binding.play_key() != play_key:
            raise ExecutionBlocked('SCOPE_PAID_REFRESH_NOT_REVIEWED')
        with r.c.engine.journal.read() as db:
            r._bound(db)
            rows = db.execute("SELECT cycle_key,result_json FROM execution_option_opportunities "
                              "WHERE status='STARTED' LIMIT 2").fetchall()
            if len(rows) != 1:
                raise ExecutionBlocked('SCOPE_PAID_REFRESH_CYCLE_REQUIRED')
            key, raw = rows[0]
            evidence = json.loads(raw or '{}')
            request, result = validate_stored(db, key, evidence, r.c.scope_policy)
        if (not result.plan.scope or request.packet.scope.binding.play_key != play_key
                or not request.packet.as_of <= now < request.packet.valid_until):
            raise ExecutionBlocked('SCOPE_PAID_REFRESH_DECISION_EXPIRED')
        ticket = dict(cycle_key=key, play_key=play_key, binding_sha256=fingerprint(binding),
                      request_hash=fingerprint(request), requested_at=now.isoformat(),
                      valid_until=request.packet.valid_until.isoformat())
        if feed.db.execute('SELECT 1 FROM scope_refresh_requests WHERE cycle_key=?', (key,)).fetchone():
            raise ExecutionBlocked('SCOPE_PAID_REFRESH_ALREADY_REQUESTED')
        feed.db.execute('INSERT INTO scope_refresh_requests VALUES(?,?,?,\'QUEUED\',NULL,NULL)',
                        (key, json.dumps(ticket, sort_keys=True), fingerprint(ticket)))
        feed.db.commit()
        completed = asyncio.get_running_loop().create_future()
        self.pending = (ticket, completed)
        self.wake.set()
        try:
            outcome = await asyncio.shield(completed)
            if outcome['status'] != 'DELIVERED':
                raise ScopeRefreshUnavailable('SCOPE_PAID_REFRESH_' + outcome['status'])
            while not self.stop.is_set() and r.c.now() < request.packet.valid_until:
                packet = r.scope.latest
                if packet is not None and packet.sequence >= outcome['sequence']:
                    return await r.scope.fresh(play_key)
                await asyncio.sleep(0.01)
            raise ScopeRefreshUnavailable('SCOPE_PAID_REFRESH_DELIVERY_EXPIRED')
        except asyncio.CancelledError:
            # The caller's original timeout never cancels independent collection
            # or protection. A completed late read remains original feed evidence.
            feed.db.execute("UPDATE scope_refresh_requests SET status='CANCELLED' WHERE cycle_key=? "
                            "AND status IN ('QUEUED','CAPTURING')", (key,))
            feed.db.commit()
            completed.cancel()
            raise

    async def collect(self, operation, *, now):
        item = self.pending
        if item is None:
            self.wake.clear()
            return
        ticket, future = item
        try:
            if self.stop.is_set() or future.cancelled():
                outcome = {'status': 'CANCELLED'}
            elif now >= datetime.fromisoformat(ticket['valid_until']):
                outcome = {'status': 'EXPIRED'}
            else:
                outcome = await operation(ticket)
            self.feed.db.execute(
                "UPDATE scope_refresh_requests SET result_json=?,status=CASE WHEN status='CANCELLED' "
                "THEN status ELSE ? END WHERE cycle_key=?",
                (json.dumps(outcome, sort_keys=True), outcome['status'], ticket['cycle_key']))
            self.feed.db.commit()
            if not future.done():
                future.set_result(outcome)
        finally:
            self.pending = None
            self.wake.clear()

    async def wait(self, seconds):
        tasks = [asyncio.create_task(self.stop.wait()), asyncio.create_task(self.wake.wait())]
        try:
            await asyncio.wait(tasks, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
