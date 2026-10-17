"""Sticky pre-entry Swing retirement in the existing fenced owner journal."""

from app.execution.engine import ExecutionBlocked
from app.options.engine import fingerprint
from app.options.swing import SwingTerminal, seed_issues


def completed_invalidation(scan, history, intraday, policy, calendar, symbols):
    """Inspect only validated, completed target-session bars; no quote inference."""
    seed, at = scan.seed, scan.evaluated_at
    window = calendar.current_window(at)
    if (
        seed.created_at > at
        or seed_issues(seed, policy, calendar, symbols)
        or intraday.issues
        or intraday.symbol != seed.history.symbol
        or intraday.evaluated_at != at
        or window is None
        or window.session_date != seed.target_session.isoformat()
    ):
        return None
    stop = scan.observations[0].invalidation
    call = seed.instrument.contract.right == "CALL"
    for bar in history.bars:
        if bar.ends_at <= min(at, history.source_at, history.received_at) and (
            bar.low <= stop if call else bar.high >= stop
        ):
            return SwingTerminal(
                seed_hash=fingerprint(seed),
                status="INVALIDATED",
                observed_at=at,
                triggered_at=bar.ends_at,
                invalidation=stop,
                history_hash=fingerprint(history),
            )
    return None


def apply_terminal(scan, terminal):
    if terminal is None:
        return scan
    reason = "SWING_SEED_" + terminal.status
    observation = scan.observations[0]
    return scan.model_copy(
        update={
            "terminal": terminal,
            "issues": tuple(dict.fromkeys((*scan.issues, reason))),
            "observations": (
                observation.model_copy(
                    update={
                        "status": "BLOCKED",
                        "reasons": tuple(dict.fromkeys((*observation.reasons, reason))),
                    }
                ),
            ),
        }
    )


def load_terminal(db, seed):
    digest = fingerprint(seed)
    row = db.execute(
        "SELECT terminal_json FROM execution_option_swing_terminals WHERE seed_hash=?", (digest,)
    ).fetchone()
    if row is None:
        return None
    terminal = SwingTerminal.model_validate_json(row[0])
    if terminal.seed_hash != digest:
        raise ExecutionBlocked("SWING_TERMINAL_BINDING_MISMATCH")
    return terminal


def retain_terminal(c, db, seed, terminal):
    """First terminal evidence wins, including when later history is revised."""
    if terminal is None or load_terminal(db, seed) is not None:
        return
    digest = fingerprint(seed)
    row = db.execute(
        "SELECT seed_hash FROM execution_option_swing_seeds WHERE session=? AND symbol=?",
        (seed.target_session.isoformat(), seed.history.symbol),
    ).fetchone()
    if row is None or row[0] != digest or terminal.seed_hash != digest:
        raise ExecutionBlocked("SWING_TERMINAL_SEED_LOCK_REQUIRED")
    db.execute(
        "INSERT INTO execution_option_swing_terminals VALUES(?,?)",
        (digest, terminal.model_dump_json()),
    )
    c.engine.journal.event(
        db,
        c.now(),
        "SWING_SEED_TERMINAL",
        {
            "session": seed.target_session.isoformat(),
            "symbol": seed.history.symbol,
            "terminal": terminal.model_dump(mode="json"),
        },
    )


def retire_expired(c, db, seed):
    close = c.engine.calendar.calendar.session_close(
        seed.target_session.isoformat()
    ).to_pydatetime()
    if c.now() >= close:
        retain_terminal(
            c,
            db,
            seed,
            SwingTerminal(
                seed_hash=fingerprint(seed),
                status="EXPIRED",
                observed_at=c.now(),
                triggered_at=close,
            ),
        )


def retain_scans(c, scans):
    with c.engine.journal.write() as db:
        c._bound(db)
        for scan in scans:
            if scan.version == "swing-next-session-v1" and scan.terminal is not None:
                retain_terminal(c, db, scan.seed, scan.terminal)
