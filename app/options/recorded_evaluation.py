"""Bind paired ledger assertions to the exact sealed common market observations."""

from app.options.engine import fingerprint
from app.options.market_tape import MAX_TAPE_BYTES, RecordedTape


def tape_issues(bundle, tapes):
    """Validate content, not provider authenticity or strategy/portfolio provenance."""
    if len(tapes) > 60:
        raise ValueError("Tape count exceeds session capacity")
    validated, size = {}, 0
    for value in tapes:
        tape = RecordedTape.model_validate(value.model_dump(warnings=False))
        size += len(tape.model_dump_json().encode())
        if size > 2 * MAX_TAPE_BYTES:
            raise ValueError("Combined tape evidence capacity exceeded")
        if tape.header.session_key in validated:
            raise ValueError("Duplicate session tape")
        validated[tape.header.session_key] = tape
    manifest = bundle.manifest
    if not set(validated) <= {s.key for s in manifest.sessions}:
        raise ValueError("Unenrolled tape session")
    issues = {}
    for session in manifest.sessions:
        reasons = issues[session.key] = []
        tape = validated.get(session.key)
        if tape is None:
            reasons.append("SEALED_MARKET_TAPE_MISSING")
            continue
        h = tape.header
        if (h.experiment_id, h.declared_at, h.opens_at, h.closes_at, tape.digest) != (
            manifest.experiment_id,
            manifest.declared_at,
            session.opens_at,
            session.closes_at,
            session.tape_hash,
        ) or h.limits.model_dump(exclude={"account_id", "population_id"}) != manifest.arms[
            0
        ].limits.model_dump(exclude={"account_id", "population_id"}):
            reasons.append("RECORDED_TAPE_BINDING_MISMATCH")
            continue
        cycles = {e.cycle_key: e for e in tape.events if e.kind == "CYCLE"}
        expected = {
            "degen:" + str(t // 300)
            for t in range(int(h.opens_at.timestamp()), int(h.closes_at.timestamp()), 300)
        }
        if set(cycles) != expected:
            reasons.append("RECORDED_CYCLE_COVERAGE_INCOMPLETE")
        quotes, underlyings = {}, set()
        for event in tape.events:
            for q in event.frame.quotes:
                quotes.setdefault(fingerprint(q), event.recorded_at)
            underlyings.update(fingerprint(q) for q in event.frame.underlyings)
        for arm in (a for a in bundle.evidence if a.session_key == session.key):
            for c in arm.cycles:
                e = cycles.get(c.key)
                if e is None or c.frame_hash != fingerprint(e.frame):
                    reasons.append("CYCLE_FRAME_NOT_RECORDED")
            for call in arm.calls:
                e = cycles.get(call.source_key)
                if e is None or call.started_at < e.recorded_at:
                    reasons.append("MODEL_STARTED_BEFORE_RECORDED_INPUT")
            for order in arm.orders:
                if order.intent.side == "BUY":
                    e = cycles.get(order.intent.source_key)
                    if e is None or order.decision_completed_at < e.recorded_at:
                        reasons.append("ENTRY_DECIDED_BEFORE_RECORDED_INPUT")
                for fill in order.observation.fills if order.observation else ():
                    available_at = quotes.get(fingerprint(fill.quote))
                    if available_at is None or available_at > fill.occurred_at:
                        reasons.append("FILL_QUOTE_NOT_RECORDED_BY_FILL_TIME")
        benchmark = next((b for b in bundle.benchmarks if b.session_key == session.key), None)
        if benchmark is None or any(
            fingerprint(q) not in underlyings for q in (benchmark.start, benchmark.end)
        ):
            reasons.append("SPY_BOUNDARY_NOT_RECORDED")
        issues[session.key] = sorted(set(reasons))
    return issues
