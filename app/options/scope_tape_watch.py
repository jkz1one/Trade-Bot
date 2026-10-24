"""Account-free watch instructions bound to exact sealed Scope observations."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.options.engine import fingerprint
from app.options.market_tape import MAX_EVENTS, RecordedTape
from app.options.models import Name, OptionRecord
from app.options.scope_replay import ScopeReplayStep
from app.options.scope_watch import ScopeWatchChoice


class ScopeTapeWatchAction(OptionRecord):
    version: Literal["scope-tape-watch-action-v1"] = "scope-tape-watch-action-v1"
    key: Name
    kind: Literal[
        "CALL", "OBSERVE_ARMING", "REVIEW_ADMISSION", "ADVANCE", "NEUTRALIZE", "OBSERVE_QUOTE"
    ]
    at: datetime
    play_key: Name
    sequence: int | None = Field(default=None, strict=True, ge=1, le=MAX_EVENTS)
    choice: ScopeWatchChoice | None = None

    @model_validator(mode="after")
    def exact_action(self):
        if self.kind == "CALL":
            if self.key != self.play_key or self.choice is None or self.sequence is None:
                raise ValueError("Tape CALL requires its own play key, choice and observation")
        elif self.choice is not None:
            raise ValueError("Only tape CALL selects a locked choice")
        if self.kind == "NEUTRALIZE" and self.sequence is None:
            raise ValueError("Tape neutral reset requires a recorded observation")
        return self


def resolve_scope_watch_action(tape, action):
    """Resolve evidence, never an admission, revision, refreshed timestamp or authority.

    Delayed actions use the original observation unchanged; native freshness and
    cutoff checks decide whether it remains usable. An absent sequence deliberately
    supplies missing evidence, including for a timer-only cutoff advance.
    """
    tape = RecordedTape.model_validate(tape.model_dump(warnings=False))
    return _resolve(tape, action)


def resolve_scope_watch_actions(tape, actions):
    """Validate the common tape once for a bounded replay request."""
    tape = RecordedTape.model_validate(tape.model_dump(warnings=False))
    if not 1 <= len(actions) <= 200:
        raise ValueError("Bounded Scope watch action sequence required")
    return tuple(_resolve(tape, action) for action in actions)


def _resolve(tape, action):
    action = ScopeTapeWatchAction.model_validate(action.model_dump(warnings=False))
    if tape.header.scope is None:
        raise ValueError("Frozen Scope tape enrollment required for watch replay")
    if not tape.header.opens_at <= action.at <= tape.header.closes_at + timedelta(seconds=5):
        raise ValueError("Scope watch action outside the recorded session")
    event = None
    if action.sequence is not None:
        event = next((e for e in tape.available(action.at) if e.sequence == action.sequence), None)
        if event is None or event.frame.scope is None:
            raise ValueError("Referenced Scope observation is not available")
        if event.frame.scope.play_key != action.play_key:
            raise ValueError("Referenced Scope play identity mismatch")
    item = event.frame.scope if event is not None else None
    step = ScopeReplayStep(
        key=action.key,
        kind=action.kind,
        at=action.at,
        play_key=action.play_key,
        choice=action.choice,
        frame=item.frame if item is not None and action.kind != "OBSERVE_QUOTE" else None,
        context=(
            item.context
            if item is not None and action.kind in {"CALL", "OBSERVE_ARMING", "REVIEW_ADMISSION"}
            else None
        ),
        underlying=(
            item.underlying
            if item is not None and action.kind in {"REVIEW_ADMISSION", "OBSERVE_QUOTE"}
            else None
        ),
    )
    binding = {
        "tape_hash": tape.digest,
        "policy_hash": fingerprint(tape.header.scope),
        "sequence": action.sequence,
        "event_hash": fingerprint(event) if event is not None else None,
        "input_hash": fingerprint(item) if item is not None else None,
        "recorded_at": event.recorded_at.isoformat() if event is not None else None,
        "resolved_step_hash": fingerprint(step),
    }
    return step, binding
