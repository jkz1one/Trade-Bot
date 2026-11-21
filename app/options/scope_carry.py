"""Explicit combined owner enrollment; individual holdings retain their native terms."""


def validate_enrollment(
    owner, scope, swing, entry=None, position=None, *, replay=False, replay_enrollment=None
):
    """Used before owner creation and again when reconstructing stored evidence."""
    from app.mixed.replay_enrollment import MixedReplayEnrollment
    from app.options.scope_replay_enrollment import ScopeCarrySeriesEnrollment

    replay_carry = type(replay_enrollment) is ScopeCarrySeriesEnrollment
    mixed = type(replay_enrollment) is MixedReplayEnrollment
    if mixed and (
        not replay
        or owner.mixed_owner is None
        or owner.mixed_owner.reasoning != "mixed-paid-entry-v1"
        or entry is None
        or entry.mixed_selection != "mixed-paid-entry-v1"
    ):
        raise ValueError("Complete mixed carry replay enrollment required")
    if replay_carry and (not replay or owner.scope_carry is None):
        raise ValueError("Combined carry replay requires its exact owner enrollment")
    combined = scope is not None and owner.swing_carry is not None
    marked = any(
        p is not None and p.scope_carry is not None for p in (owner, scope, entry, position)
    )
    if replay and (combined or marked) and not (replay_carry or mixed):
        raise ValueError("Complete matching shared Scope carry enrollment required")
    validate_policy(owner, scope, swing, entry, position, shortlist=replay_carry)


def validate_policy(owner, scope, swing, entry=None, position=None, *, shortlist=False):
    """Pure policy coherence; grants neither replay enrollment nor execution authority."""
    parts = (owner, scope, entry, position)
    marked = [p for p in parts if p is not None and p.scope_carry is not None]
    combined = scope is not None and owner.swing_carry is not None
    if not combined and not marked:
        if scope is not None and swing is not None and swing.carry is not None:
            raise ValueError("Complete matching shared Scope carry enrollment required")
        return
    if (
        not combined
        or swing is None
        or swing.carry is None
        or owner.scope_carry != "shared-scope-carry-v1"
        or scope.version != owner.scope_arbitration
        or scope.scope_carry != owner.scope_carry
        or set(scope.family_priority) != {"DEGEN", "SWING", "SCOPE"}
        or (
            scope.version == "shared-scope-entry-v1"
            and (
                entry is None
                or entry.scope_carry != owner.scope_carry
                or entry.scope_selection
                not in (
                    {"scope-fixed-plan-v1", "scope-fixed-shortlist-v1"}
                    if shortlist
                    else {"scope-fixed-plan-v1"}
                )
                or entry.max_carry_horizon_seconds is None
            )
        )
        or (
            position is not None
            and (
                position.scope_carry != owner.scope_carry
                or position.swing_carry != owner.swing_carry
                or position.scope_management != "scope-fixed-position-v1"
            )
        )
    ):
        raise ValueError("Complete matching shared Scope carry enrollment required")
