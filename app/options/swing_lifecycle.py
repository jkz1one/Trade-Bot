"""Sticky pre-entry Swing retirement in the existing fenced owner journal."""

from app.options.models import paper_market_evidence
from app.execution.engine import ExecutionBlocked
from app.options.engine import exact, fingerprint
from app.options.swing import SwingSeed, SwingTerminal, seed_issues


def completed_terminal(scan, history, intraday, policy, calendar, symbols):
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
        if bar.ends_at > min(at, history.source_at, history.received_at):
            continue
        # A bar gives no within-bar order. Prefer invalidation when both were touched.
        if bar.low <= stop if call else bar.high >= stop:
            return SwingTerminal(
                seed_hash=fingerprint(seed),
                status="INVALIDATED",
                observed_at=at,
                triggered_at=bar.ends_at,
                invalidation=stop,
                history_hash=fingerprint(history),
            )
        if policy.unfilled_lifecycle == "observed-lifecycle-v3" and (
            bar.high >= seed.first_target if call else bar.low <= seed.first_target
        ):
            return SwingTerminal(
                seed_hash=fingerprint(seed),
                status="TARGET_CONSUMED",
                observed_at=at,
                triggered_at=bar.ends_at,
                first_target=seed.first_target,
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
    return retain_owned_terminal(c.engine, db, seed, terminal, c.now())


def retain_owned_terminal(engine, db, seed, terminal, now):
    """First terminal evidence wins, including when later history is revised."""
    if terminal is None or load_terminal(db, seed) is not None:
        return
    digest = fingerprint(seed)
    from app.options.swing_batch import seed_lock

    row = seed_lock(db, seed)
    if row is None or row[0] != digest or terminal.seed_hash != digest:
        raise ExecutionBlocked("SWING_TERMINAL_SEED_LOCK_REQUIRED")
    db.execute(
        "INSERT INTO execution_option_swing_terminals VALUES(?,?)",
        (digest, terminal.model_dump_json()),
    )
    engine.journal.event(
        db,
        now,
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


@exact
def quote_terminal(seed, policy, limits, calendar, quote, now):
    """Use only an observed, fresh, uncrossed quote for the locked target session."""
    from decimal import ROUND_CEILING, ROUND_FLOOR

    from app.options.degen import _metric
    from app.options.governor import _fresh

    if (
        policy.unfilled_lifecycle not in ("observed-invalidation-v2", "observed-lifecycle-v3")
        or quote is None
    ):
        return None
    window = calendar.current_window(now)
    if (
        seed.created_at > now
        or seed_issues(seed, policy, calendar, limits.allowed_underlyings)
        or window is None
        or window.session_date != seed.target_session.isoformat()
        or not window.opens_at <= quote.source_at <= now < window.closes_at
        or quote.symbol != seed.history.symbol
        or quote.source != limits.underlying_source
        or not quote.complete
        or not paper_market_evidence(quote)
        or not limits.minimum_underlying_price <= quote.bid <= quote.ask
        or not _fresh(
            quote.source_at,
            quote.received_at,
            now,
            limits.quote_max_age_seconds,
            limits.max_receive_lag_seconds,
        )
    ):
        return None
    call = seed.instrument.contract.right == "CALL"
    bar = seed.history.bars[-1]
    stop = _metric(
        bar.low * (1 - policy.stop_buffer_fraction)
        if call
        else bar.high * (1 + policy.stop_buffer_fraction),
        ROUND_CEILING if call else ROUND_FLOOR,
    )
    if any(p is not None for p in (policy.daily_base, policy.ma_pullback, policy.higher_levels)):
        # seed_issues above already reconstructed the original family and target proof.
        stop = seed.target_geometry.invalidation
    if quote.bid <= stop if call else quote.ask >= stop:
        return SwingTerminal(
            seed_hash=fingerprint(seed),
            status="INVALIDATED",
            observed_at=now,
            triggered_at=quote.source_at,
            invalidation=stop,
            quote=quote,
        )
    if policy.unfilled_lifecycle == "observed-lifecycle-v3" and (
        quote.bid >= seed.first_target if call else quote.ask <= seed.first_target
    ):
        return SwingTerminal(
            seed_hash=fingerprint(seed),
            status="TARGET_CONSUMED",
            observed_at=now,
            triggered_at=quote.source_at,
            first_target=seed.first_target,
            quote=quote,
        )
    return None


def observe_quotes(c, underlyings):
    if c.swing_policy is None or c.swing_policy.unfilled_lifecycle not in (
        "observed-invalidation-v2",
        "observed-lifecycle-v3",
    ):
        return
    at = c.now()
    window = c.engine.calendar.current_window(at)
    if window is None:
        return
    with c.engine.journal.write() as db:
        ledger = c._bound(db)
        if (
            ledger.position is not None
            or db.execute(
                "SELECT 1 FROM execution_orders WHERE active_lock IS NOT NULL AND (status!='PREPARED' OR attempted_at IS NOT NULL) LIMIT 1"
            ).fetchone()
        ):
            return
        rows = db.execute(
            "SELECT seed_json FROM execution_option_swing_seeds WHERE session=?",
            (window.session_date,),
        ).fetchall()
        if c.swing_policy.family_batch is not None:
            rows += db.execute(
                "SELECT s.seed_json FROM execution_option_swing_batch_seeds s JOIN execution_option_swing_batches b ON s.batch_hash=b.batch_hash WHERE b.session=?",
                (window.session_date,),
            ).fetchall()
        for row in rows:
            seed = SwingSeed.model_validate_json(row[0])
            quotes = [q for q in underlyings if q.symbol == seed.history.symbol]
            if len(quotes) == 1:
                retain_terminal(
                    c,
                    db,
                    seed,
                    quote_terminal(
                        seed, c.swing_policy, c.engine.limits, c.engine.calendar, quotes[0], at
                    ),
                )
