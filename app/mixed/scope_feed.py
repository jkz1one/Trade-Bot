"""Reviewed single-watch Scope delivery. Missing originals never authorize a watch."""
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from app.options.models import OptionInstrument, OptionRecord
from app.options.scope import ScopeSession
from app.options.scope_structure import PRICE_PATTERNS
from app.options.scope_watch import ScopeWatchChoice


class ScopeFeedBinding(OptionRecord):
    version: Literal['robinhood-scope-feed-v1'] = 'robinhood-scope-feed-v1'
    session: ScopeSession
    previous_session: date
    instrument: OptionInstrument
    choice: ScopeWatchChoice
    contract_capture_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def exact(self):
        i, c = self.instrument, self.instrument.contract
        if (i.provider != 'robinhood' or not i.metadata_complete or not i.option_tradable
                or i.simulation_terms is not None or c.underlying != 'SPX' or c.root != 'SPXW'
                or c.underlying_kind != 'INDEX' or c.expiration != self.session.session_date
                or c.settlement_session != 'PM' or c.exercise_style != 'EUROPEAN'
                or c.settlement != 'CASH' or c.multiplier != 100 or c.adjusted
                or c.last_trading_at < self.session.protect_at
                or self.previous_session >= self.session.session_date
                or self.choice.right != c.right or self.choice.pattern not in PRICE_PATTERNS
                or self.choice.parent_pattern != self.choice.pattern):
            raise ValueError('Exact reviewed SPXW terms, calendar and price pattern required')
        return self

    def play_key(self):
        from app.options.engine import fingerprint
        return 'scope-rh-' + fingerprint(self)[:32]


def owner_state(observer, binding):
    """Read the native watch status; collector never writes the owner journal."""
    import json
    with observer.read() as db:
        rows = db.execute('SELECT play_key,record_json FROM execution_option_scope_watches WHERE active_lock=1').fetchall()
        own = db.execute('SELECT record_json FROM execution_option_scope_watches WHERE play_key=?',
                         (binding.play_key(),)).fetchone()
    if rows and rows[0]['play_key'] != binding.play_key():
        raise ValueError('Different active Scope watch requires its original binding')
    return json.loads(own[0]) if own else None


def deliver(binding, captured, frame, metadata, *, now, settings, sequence, record=None):
    """Return native frame/action with only original clocks and native watch choices."""
    from app.mixed.scope_sources import assemble, map_index
    from app.options.coordinator import DegenFrame
    from app.options.runtime_models import ScopeRuntimeAction
    from app.options.scope_arbitration import ScopeCycleInput
    from app.options.scope import preflight_scope
    from app.options.scope_read import validate
    from app.options.scope_structure import scan_scope_structure
    if settings.limits.mode != 'PAPER' or settings.scope_policy is None:
        raise ValueError('Explicit PAPER Scope owner required')
    policy = settings.scope_policy.watch.context.structure.preflight
    if policy.input_basis is None or policy.session_source != binding.session.source:
        raise ValueError('Reviewed Scope price/session policy required')
    if captured is None or captured.operation != 'SCOPE_INPUT' or captured.status != 'COMPLETE':
        return frame, None, ('SCOPE_INDEX_CAPTURE_UNAVAILABLE',)
    validate(captured.observations, captured.started_at, complete=True)
    if not captured.started_at <= captured.collected_at <= now:
        raise ValueError('Scope capture clocks invalid')
    ref, history, report = map_index(*captured.observations, binding.session, now=now)
    # A valid current index value remains protection evidence even if bar provenance fails.
    frame = DegenFrame.model_validate(frame.model_dump() | {'held_underlyings': (ref,)})
    if record is not None and record.get('status') == 'WATCHING' and record.get('geometry'):
        from app.options.scope_quote import price_status
        from app.options.scope_structure import ScopeGeometry
        if price_status(ScopeGeometry.model_validate(record['geometry']), ref) != 'OBSERVED':
            from app.options.scope import ScopePreflightInput
            from app.options.scope_context import ScopeContextInput
            from app.mixed.observed_simulation import annotate
            quotes = [q for q in (*frame.quotes, *frame.held_quotes) if q.instrument == binding.instrument]
            metas = [m for m in metadata if m.instrument == binding.instrument]
            original = ScopePreflightInput.model_validate(record['reviewed_frame'])
            supplied = original.model_copy(update={'quote': annotate(quotes[0]) if len(quotes)==1 else None,
                'metadata': annotate(metas[0]) if len(metas)==1 else None, 'index_reference': ref})
            item = ScopeCycleInput(play_key=binding.play_key(), frame=supplied,
                context=ScopeContextInput.model_validate(record['locked_context']), underlying=ref)
            action = ScopeRuntimeAction(key=f'{binding.play_key()}:{sequence}', kind='OBSERVE_QUOTE', play_key=binding.play_key())
            frame = annotate(frame)
            return DegenFrame.model_validate(frame.model_dump() | {'scope': item}), action, tuple(report['issues'])
    if history is None:
        return frame, None, tuple(report['issues'])
    matches = [q for q in (*frame.quotes, *frame.held_quotes) if q.instrument == binding.instrument]
    metas = [m for m in metadata if m.instrument == binding.instrument]
    if len(matches) != 1 or len(metas) != 1 or len(frame.histories) != 2:
        return frame, None, ('SCOPE_EXACT_MARKET_COVERAGE_UNAVAILABLE',)
    supplied, context = assemble(binding.session, history, frame.histories, metas[0], matches[0],
                                previous_session=binding.previous_session, index_reference=ref)
    if preflight_scope(supplied, policy, now=now).blockers:
        return frame, None, ('SCOPE_PREFLIGHT_BLOCKED',)
    frame = DegenFrame.model_validate(frame.model_dump() | {
        'quotes': tuple(supplied.quote if q.instrument == binding.instrument else q for q in frame.quotes),
        'held_quotes': tuple(supplied.quote if q.instrument == binding.instrument else q for q in frame.held_quotes)})
    play = binding.play_key()
    item = ScopeCycleInput(play_key=play, frame=supplied, context=context, underlying=ref)
    if record is None:
        scan = scan_scope_structure(supplied, settings.scope_policy.watch.context.structure, now=now)
        if not any(o.pattern == binding.choice.pattern and o.right == binding.choice.right
                   and o.status == 'DETECTED' for o in scan.observations):
            return frame, None, ('SCOPE_PATTERN_NOT_PRESENT',)
        action = ScopeRuntimeAction(key=play, kind='CALL', play_key=play, choice=binding.choice)
    elif record.get('arming', {}).get('status') == 'ARMED':
        action = None
    elif record['status'] in {'WATCHING', 'ARMING'}:
        action = ScopeRuntimeAction(key=f'{play}:{sequence}', kind='OBSERVE_ARMING', play_key=play)
    elif record['status'] in {'ARMED', 'ORDER_WORKING', 'POSITION_OPEN'}:
        action = None
    else:
        # A consumed or terminal play is never re-created after a restart.
        return frame, None, ()
    return DegenFrame.model_validate(frame.model_dump() | {'scope': item}), action, ()
