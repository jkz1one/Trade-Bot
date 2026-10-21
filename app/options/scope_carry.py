"""Explicit combined owner enrollment; individual holdings retain their native terms."""


def validate_enrollment(owner, scope, swing, entry=None, position=None, *, replay=False):
    """Used before owner creation and again when reconstructing stored evidence."""
    parts = (owner, scope, entry, position)
    marked = [p for p in parts if p is not None and p.scope_carry is not None]
    combined = scope is not None and owner.swing_carry is not None
    if not combined and not marked:
        if scope is not None and swing is not None and swing.carry is not None:
            raise ValueError("Complete matching shared Scope carry enrollment required")
        return
    if (
        not combined
        or replay
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
                or entry.scope_selection != "scope-fixed-plan-v1"
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
