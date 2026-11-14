"""Deterministic whole-session diagnostics over the evaluator's verified net results."""

import hashlib
from decimal import Context, Decimal, localcontext

from app.options.evaluation_models import EvaluationManifest

ZERO = Decimal(0)


def _starts(seed: int, count: int):
    """Versioned SHA256 counter stream, unbiased rejection to a bounded index."""
    ceiling = 2**256 - (2**256 % count)
    counter = 0
    while True:
        value = int.from_bytes(
            hashlib.sha256(f"paired-circular-block-v1:{seed}:{counter}".encode()).digest()
        )
        counter += 1
        if value < ceiling:
            yield value % count


def _quantile(values, probability):
    """Linear interpolation at (n - 1) * p on ascending exact-decimal samples."""
    position = (len(values) - 1) * probability
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def _bootstrap(values, policy):
    n = len(values)
    starts = _starts(policy.seed, n)
    samples = []
    for _ in range(policy.replicates):
        total, remaining = ZERO, n
        while remaining:
            start = next(starts)
            size = min(policy.block_sessions, remaining)
            total += sum((values[(start + offset) % n] for offset in range(size)), ZERO)
            remaining -= size
        samples.append(total / n)
    samples.sort()
    tail = (1 - policy.confidence) / 2
    return _quantile(samples, tail), _quantile(samples, 1 - tail)


def session_analysis(manifest: EvaluationManifest, rows: list[dict]) -> dict:
    """Called after all accounting/tape/baseline gates. Does not drop missing rows."""
    with localcontext(Context(prec=192)):
        return _analysis(manifest, rows)


def _analysis(manifest, rows):
    policy = manifest.session_analysis
    if policy is None:
        return {"status": "NOT_ENROLLED"}
    # Keep the declared ordering and denominator even for absent evidence.
    by_session = {row["session"]: row for row in rows}
    values = []
    for session in manifest.sessions:
        row = by_session.get(session.key)
        value = (
            row["paired_net_difference"].get(policy.primary_arm)
            if row is not None and row["status"] == "COMPLETE"
            else None
        )
        values.append(Decimal(value) if value is not None else None)
    complete = all(v is not None for v in values)
    groups = {}
    for index, (session, value) in enumerate(zip(manifest.sessions, values, strict=True)):
        labels = [
            ("chronological_block", str(index // policy.block_sessions + 1)),
            ("calendar_month", session.key[:7]),
        ]
        if policy.regime_labels:
            labels.append(("declared_regime", policy.regime_labels[index]))
        for kind, label in labels:
            groups.setdefault((kind, label), []).append((session.key, value))
    concentration = []
    for (kind, label), members in groups.items():
        known = [value for _, value in members if value is not None]
        concentration.append(
            {
                "kind": kind,
                "label": label,
                "sessions": [key for key, _ in members],
                "planned_sessions": len(members),
                "complete_sessions": len(known),
                "net_difference_sum": str(sum(known, ZERO)) if len(known) == len(members) else None,
            }
        )
    interval, mean, share = None, None, None
    if complete:
        mean = sum(values, ZERO) / len(values)
        lower, upper = _bootstrap(values, policy)
        interval = {
            "lower": str(lower),
            "upper": str(upper),
            "lower_minus_hurdle": str(lower - manifest.hurdle_per_session),
            "upper_minus_hurdle": str(upper - manifest.hurdle_per_session),
        }
        absolute_total = sum((abs(v) for v in values), ZERO)
        share = max(abs(v) for v in values) / absolute_total if absolute_total else None
    return {
        "status": "COMPLETE_DIAGNOSTIC" if complete else "INCONCLUSIVE",
        "economic_conclusion": "INCONCLUSIVE",
        "execution_authority": False,
        "policy": policy.model_dump(mode="json"),
        "endpoint": f"{policy.primary_arm}_minus_A_net_equity_per_session",
        "review_after": manifest.sessions[-1].closes_at.isoformat(),
        "planned_sessions": len(values),
        "complete_sessions": sum(v is not None for v in values),
        "reasons": [] if complete else ["INCOMPLETE_DECLARED_HORIZON"],
        "mean_net_difference": str(mean) if mean is not None else None,
        "percentile_interval": interval,
        "largest_absolute_session_share": str(share) if share is not None else None,
        "concentration": concentration,
        "regime_coverage": "DECLARED_LABELS_ONLY" if policy.regime_labels else "NOT_PROVIDED",
        "limitations": [
            "Fixture diagnostic only; no prospective evidence or economic acceptance",
            "Circular blocks wrap last to first session; dependence and stationarity are assumptions",
            "Block length, sample size and percentile coverage are not validated by this calculation",
            "One frozen primary arm; other arms and D-minus-C remain descriptive",
            "Declared trials are unverified; no multiple-testing or repeated-peeking correction",
            "Regime labels are predeclared metadata, not verified market classifications",
        ],
    }
