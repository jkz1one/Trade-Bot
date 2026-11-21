"""Pinned Scope price ceilings narrow the shared fee-inclusive governor."""

from decimal import Decimal, localcontext

import pytest
from test_option_scope_owned_admission import evidence, review, start
from test_option_scope_watch import owned, ready

from app.options.governor import admit_option
from app.options.models import OptionAccount, OptionLimits, OptionProposal, SessionWindow
from app.options.scope_admission import scope_quantity_cap

D = Decimal


@pytest.mark.parametrize(
    "ask,cap",
    [
        (".20", 4),
        ("1.25", 4),
        ("1.250000000001", 3),
        ("1.65", 3),
        ("1.650000000001", 2),
        ("2.50", 2),
        ("2.500000000001", 1),
        ("5", 1),
    ],
)
def test_exact_ask_boundaries_do_not_round_into_a_larger_tier(ask, cap):
    with localcontext() as ctx:
        ctx.prec = 3
        assert scope_quantity_cap(D(ask)) == cap


@pytest.mark.parametrize(
    "ask", [D(".199999999999"), D("5.000000000001"), D("NaN"), D("Infinity"), True, "1.25", None]
)
def test_invalid_price_cannot_produce_a_quantity_ceiling(ask):
    with pytest.raises(ValueError):
        scope_quantity_cap(ask)


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize(
    "ask,cap,quantity",
    [
        (".20", 4, 4),
        ("1.00", 4, 4),
        ("1.25", 4, 3),
        ("1.30", 3, 3),
        ("1.65", 3, 2),
        ("1.70", 2, 2),
        ("2.50", 2, 1),
        ("2.55", 1, 1),
        ("5.00", 1, 0),
    ],
)
def test_stored_tier_and_common_governor_keep_slippage_and_all_fees(
    tmp_path, right, ask, cap, quantity
):
    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue, right)
        fresh, context, underlying, now = evidence(engine, f)
        fresh = fresh.model_copy(
            update={
                "metadata": fresh.metadata.model_copy(
                    update={"delta": D(".50") if right == "CALL" else D("-.50")}
                ),
                "quote": fresh.quote.model_copy(
                    update={"bid": D(ask), "ask": D(ask), "ask_size": 20}
                ),
            }
        )
        ready(engine, venue, now)
        stored = review(book, fresh, context, underlying, now)["record"]["admission_review"]
        assert stored["quantity_tier"] == {
            "version": "scope-price-quantity-v1",
            "ask": str(D(ask)),
            "maximum_quantity": cap,
        }
        assert stored["limits"]["max_contracts"] == 10
        assert stored["effective_limits"]["max_contracts"] == cap
        expected = admit_option(
            OptionProposal.model_validate(stored["proposal"]),
            fresh.quote,
            underlying,
            OptionAccount.model_validate(stored["account"]),
            OptionLimits.model_validate(stored["effective_limits"]),
            SessionWindow.model_validate(stored["session"]),
            now=now,
        )
        assert stored["admission"] == expected.model_dump(mode="json")
        assert expected.quantity == quantity
        assert stored["eligible"] is (quantity > 0)
        if quantity:
            assert expected.entry_debit <= D("500")
            assert expected.reserved_exit_fees > 0
            assert expected.full_premium_loss == expected.entry_debit + expected.reserved_exit_fees
        assert not stored["authority"] and not stored["live_enabled"]
        with engine.journal.read() as db:
            assert db.execute("SELECT COUNT(*) FROM execution_orders").fetchone()[0] == 0


@pytest.mark.parametrize(
    "overrides,quantity",
    [
        ({"max_contracts": 1}, 1),
        ({"max_full_premium_loss": "55.60"}, 2),
        ({"max_full_premium_loss": "55.599999999999"}, 1),
    ],
)
def test_owner_limits_remain_stricter_than_scope_tier(tmp_path, overrides, quantity):
    with owned(tmp_path, enroll=False, **overrides) as (engine, venue, _):
        book, f = start(engine, venue)
        fresh, context, underlying, now = evidence(engine, f)
        fresh = fresh.model_copy(
            update={
                "metadata": fresh.metadata.model_copy(update={"delta": D(".50")}),
                "quote": fresh.quote.model_copy(
                    update={"bid": D(".20"), "ask": D(".20"), "ask_size": 20}
                ),
            }
        )
        ready(engine, venue, now)
        stored = review(book, fresh, context, underlying, now)["record"]["admission_review"]
        assert stored["quantity_tier"]["maximum_quantity"] == 4
        assert stored["admission"]["quantity"] == quantity
        assert stored["effective_limits"]["max_contracts"] == min(4, engine.limits.max_contracts)


def test_fresh_price_replaces_tier_while_old_action_receipt_stays_historical(tmp_path):
    from test_option_scope_watch import revision

    with owned(tmp_path, enroll=False) as (engine, venue, _):
        book, f = start(engine, venue)
        results = []
        for seconds, ask in ((60, ".20"), (70, "2.55")):
            fresh, context, underlying, now = evidence(engine, f, seconds)
            fresh = fresh.model_copy(
                update={
                    "metadata": fresh.metadata.model_copy(update={"delta": D(".50")}),
                    "quote": fresh.quote.model_copy(
                        update={"bid": D(ask), "ask": D(ask), "ask_size": 20}
                    ),
                }
            )
            ready(engine, venue, now)
            kwargs = {
                "frame": fresh,
                "context": context,
                "underlying": underlying,
                "now": now,
                "expected_revision": revision(engine),
            }
            result = book.review_admission(str(seconds), "first", **kwargs)
            results.append(result)
            if seconds == 60:
                original = kwargs
        first = results[0]["record"]["admission_review"]
        latest = results[1]["record"]["admission_review"]
        assert first["quantity_tier"]["maximum_quantity"] == first["admission"]["quantity"] == 4
        assert latest["quantity_tier"]["maximum_quantity"] == latest["admission"]["quantity"] == 1
        assert book.review_admission("60", "first", **original) == results[0]
        assert book.snapshot()["watches"][0]["admission_review"] == latest
