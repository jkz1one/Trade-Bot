"""Real October 27 captures plus synthetic supplemental terms, never market acceptance."""

import copy
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.mixed.contract_catalog import bind, main, propose, review
from app.mixed.simulation_profile import configuration

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def captures():
    bundle = json.loads((FIXTURES / "connected_options_20261027.json").read_text())
    schemas = json.loads((FIXTURES / bundle["schemas_fixture"]).read_text())
    for artifact in bundle["captures"]:
        artifact["result"]["schemas"] = copy.deepcopy(schemas)
    return bundle["captures"]


def rows(artifact):
    return artifact["result"]["observations"][0]["raw"]["structuredContent"]["data"]


def terms(captures):
    # Entirely synthetic supplemental legal/session terms for code-path tests only.
    records = review(captures[0], captures[1:])["contracts"]
    return [
        {
            "provider": "robinhood",
            "instrument_id": row["provider_record"]["id"],
            "metadata_complete": True,
            "option_tradable": True,
            "contract": {
                "underlying": row["provider_record"]["chain_symbol"],
                "underlying_kind": "ETF",
                "underlying_market": "US_LISTED",
                "root": row["provider_record"]["chain_symbol"],
                "right": row["provider_record"]["type"].upper(),
                "strike": row["provider_record"]["strike_price"],
                "expiration": "2026-10-28",
                "multiplier": 100,
                "deliverable_kind": "SHARES",
                "deliverable_units": 100,
                "currency": "USD",
                "exercise_style": "AMERICAN",
                "settlement": "PHYSICAL",
                "settlement_session": "PM",
                "last_trading_at": "2026-10-28T20:15:00Z",
                "expires_at": "2026-10-28T21:30:00Z",
                "settles_at": "2026-10-29T20:00:00Z",
                "adjusted": False,
                "tick_below_three": ".01",
                "tick_at_or_above_three": ".01",
            },
        }
        for row in records
    ]


def test_real_capture_review_preserves_clocks_and_unknowns(captures):
    before = copy.deepcopy(captures)
    report = review(captures[0], captures[1:])
    assert len(report["contracts"]) == 4
    assert all(
        r["all_fresh_at_capture"] and r["source_clock_advanced"] for r in report["contracts"]
    )
    assert report["entitlement"] == "UNKNOWN" and not report["trading_ready"]
    assert report["status"] == "REVIEWED_TERMS_REQUIRED"
    assert "last_trading_at" in report["missing_terms"]
    assert report["contracts"][0]["provider_record"]["sellout_datetime"].startswith(
        "2026-10-28T19:45:00"
    )
    assert captures == before


def test_symbol_discovery_preserves_exact_identity_and_tradability(captures):
    for call, observation in zip(captures[0]["result"]["plan"]["calls"],
                                 captures[0]["result"]["observations"], strict=True):
        row = observation["raw"]["structuredContent"]["data"]["instruments"][0]
        call["arguments"].pop("chain_id")
        call["arguments"].pop("state")
        call["arguments"].pop("tradability")
        call["arguments"]["chain_symbol"] = row["chain_symbol"]
    before = copy.deepcopy(captures)
    assert len(review(captures[0], captures[1:])["contracts"]) == 4
    assert captures == before
    for key, bad in (("chain_symbol", "QQQ"), ("chain_id", "another-chain"),
                     ("state", "inactive"), ("tradability", "untradable"),
                     ("strike_price", "759"), ("expiration_date", "2026-10-29")):
        changed = copy.deepcopy(captures)
        rows(changed[0])["instruments"][0][key] = bad
        with pytest.raises(ValueError):
            review(changed[0], changed[1:])


def test_discovery_cannot_omit_chain_selector(captures):
    captures[0]["result"]["plan"]["calls"][0]["arguments"].pop("chain_id")
    with pytest.raises(ValueError, match="chain ID or symbol"):
        review(captures[0], captures[1:])


@pytest.mark.parametrize(
    "corruption",
    [
        "receipt",
        "schema",
        "partial",
        "duplicate",
        "chain",
        "expiry",
        "strike",
        "inactive",
        "pagination",
        "missing_quote",
        "plan",
        "time",
        "regress",
        "future",
        "same_clock_changed",
        "source",
        "duplicate_capture",
    ],
)
def test_rejects_inconsistent_capture_evidence(captures, corruption):
    contract, samples = captures[0], captures[1:]
    row = rows(contract)["instruments"][0]
    if corruption == "receipt":
        samples[0]["result"]["observations"][0]["label"] = "wrong"
    elif corruption == "schema":
        samples[0]["result"]["schemas"]["sha256"] = "0" * 64
    elif corruption == "partial":
        contract["result"]["observations"].pop()
    elif corruption == "duplicate":
        rows(contract)["instruments"].append(copy.deepcopy(row))
    elif corruption in ("chain", "expiry", "strike", "inactive"):
        key, val = {
            "chain": ("chain_id", "wrong"),
            "expiry": ("expiration_date", "2026-10-29"),
            "strike": ("strike_price", "759"),
            "inactive": ("state", "inactive"),
        }[corruption]
        row[key] = val
    elif corruption == "pagination":
        rows(contract)["next"] = "more"
    elif corruption == "missing_quote":
        rows(samples[0])["results"].pop()
    elif corruption == "plan":
        samples[0]["result"]["plan"]["instrument_ids"].pop()
    elif corruption == "time":
        samples[0]["result"]["started_at"] = "2026-10-27T19:00:00Z"
    elif corruption == "source":
        samples[0]["result"]["policy_sha256"] = "0" * 64
    elif corruption == "duplicate_capture":
        samples[1]["result"]["request_id"] = samples[0]["result"]["request_id"]
    else:
        q = rows(samples[1])["results"][0]["quote"]
        if corruption == "regress":
            q["updated_at"] = "2026-10-27T20:00:00Z"
        elif corruption == "future":
            q["updated_at"] = "2026-10-27T21:00:00Z"
        else:
            q["updated_at"] = rows(samples[0])["results"][0]["quote"]["updated_at"]
    with pytest.raises(ValueError):
        review(contract, samples)


def test_stale_book_is_evidence_not_freshness(captures):
    for a in captures[1:]:
        a["result"]["started_at"] = a["result"]["started_at"].replace("20:10", "20:11")
        a["result"]["collected_at"] = a["result"]["collected_at"].replace("20:10", "20:11")
    report = review(captures[0], captures[1:])
    assert not any(r["all_fresh_at_capture"] for r in report["contracts"])


def test_selected_subset_maps_real_quotes_without_restamping(captures):
    selected = terms(captures)[:1]
    report = bind(captures[0], captures[1:], selected)
    assert report["status"] == "CATALOG_PROPOSAL_READY"
    assert report["candidates"][0]["contract"]["last_trading_at"].startswith("2026-10-28T20:15")
    assert report["entitlement"] == "UNKNOWN" and not report["trading_ready"]
    assert len(report["review_sha256"]) == 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("strike", "759"),
        ("right", "CALL"),
        ("multiplier", 10),
        ("expiration", "2026-10-29"),
        ("tick_below_three", ".05"),
        ("underlying", "QQQ"),
    ],
)
def test_conflicting_native_terms_rejected(captures, field, value):
    selected = terms(captures)[:1]
    selected[0]["contract"][field] = value
    with pytest.raises(ValueError):
        bind(captures[0], captures[1:], selected)


def test_incomplete_or_ambiguous_selection_rejected(captures):
    selected = terms(captures)[:1]
    for values in ([], selected * 2, [{**selected[0], "metadata_complete": False}]):
        with pytest.raises(ValueError):
            bind(captures[0], captures[1:], values)


def test_proposal_changes_only_catalog_and_filters_target_carry(captures):
    _, base = configuration()
    before = copy.deepcopy(base)
    report, policy = propose(
        base,
        captures[0],
        captures[1:],
        terms(captures),
        date(2026, 10, 28),
        datetime(2026, 10, 27, 21, tzinfo=UTC),
    )
    assert len(policy.candidates) == 4 and not report["state_modified"]
    assert base == before
    with pytest.raises(ValueError):
        propose(
            base,
            captures[0],
            captures[1:],
            terms(captures),
            date(2026, 10, 27),
            datetime(2026, 10, 27, 21, tzinfo=UTC),
        )


def test_cli_inspects_private_files_without_auth_or_state(captures, tmp_path, capsys):
    paths = []
    for i, value in enumerate(captures):
        path = tmp_path / f"capture-{i}.json"
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        paths.append(str(path))
    assert main(["--contracts", paths[0], "--quotes", *paths[1:]]) == 0
    assert json.loads(capsys.readouterr().out)["provider_calls"] is False
    assert len(list(tmp_path.iterdir())) == 4


def test_tick_breakpoint_must_be_representable(captures):
    selected = terms(captures)[:1]
    ticks = rows(captures[0])["instruments"][0]["min_ticks"]
    ticks.update(cutoff_price="2", below_tick=".01", above_tick=".05")
    with pytest.raises(ValueError, match="Unsupported tick"):
        bind(captures[0], captures[1:], selected)
    ticks["cutoff_price"] = "3"
    selected[0]["contract"]["tick_at_or_above_three"] = ".05"
    assert bind(captures[0], captures[1:], selected)["status"] == "CATALOG_PROPOSAL_READY"


def test_cli_creates_proposal_once_and_cannot_change_existing_output(
    captures, tmp_path, capsys, monkeypatch
):
    import app.mixed.contract_catalog as module

    monkeypatch.setattr(module, "utc_now", lambda: datetime(2026, 10, 27, 21, tzinfo=UTC))
    tmp_path.chmod(0o700)
    _, base = configuration()
    files = [*captures, terms(captures), base.model_dump(mode="json")]
    paths = []
    for i, value in enumerate(files):
        path = tmp_path / f"input-{i}.json"
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        paths.append(str(path))
    output = tmp_path / "next-policy.json"
    args = [
        "--contracts",
        paths[0],
        "--quotes",
        *paths[1:4],
        "--terms",
        paths[4],
        "--base-policy",
        paths[5],
        "--target-session",
        "2026-10-28",
        "--output",
        str(output),
    ]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["proposed_policy_sha256"]
    before = output.read_bytes()
    assert main(args) == 2
    assert output.read_bytes() == before
    assert json.loads(capsys.readouterr().out)["status"] == "UNAVAILABLE"


def test_cli_rejects_duplicate_json_keys(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"status":"COMPLETE","status":"FAILED"}')
    path.chmod(0o600)
    assert main(["--contracts", str(path), "--quotes", str(path)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "UNAVAILABLE"


@pytest.mark.parametrize('field', [
    'delta', 'gamma', 'theta', 'vega', 'rho', 'implied_volatility',
    'chance_of_profit_long', 'chance_of_profit_short',
])
def test_analytic_drift_keeps_original_stale_book_and_hashes(captures, field):
    # Synthetic reproduction of the host's after-close analytics-only drift.
    original = copy.deepcopy(rows(captures[1])["results"][0]["quote"])
    original["updated_at"] = "2026-10-27T19:00:00Z"
    for i, artifact in enumerate(captures[1:]):
        q = copy.deepcopy(original)
        q[field] = str(.2 + i / 100)
        rows(artifact)["results"][0]["quote"] = q
    before = copy.deepcopy(captures)
    report = review(captures[0], captures[1:])
    item = next(c for c in report["contracts"] if c["provider_record"]["id"] == original["instrument_id"])
    assert not item["all_fresh_at_capture"] and not item["source_clock_advanced"]
    samples = item["samples"]
    assert len({s["quote_sha256"] for s in samples}) == 3
    assert len({s["non_analytic_sha256"] for s in samples}) == 1
    assert [s["analytic_changes_at_same_quote_time"] for s in samples] == [[], [field], [field]]
    assert captures == before


@pytest.mark.parametrize('field,value', [
    ('bid_price', '0.29'), ('ask_price', '0.32'), ('bid_size', 999),
    ('ask_size', 999), ('volume', 123456), ('open_interest', 123456),
    ('mark_price', '0.301'),
])
def test_same_clock_non_analytic_mutations_still_reject(captures, field, value):
    q = copy.deepcopy(rows(captures[1])["results"][0]["quote"])
    q[field] = value
    q['delta'] = '.123'
    rows(captures[2])["results"][0]["quote"] = q
    with pytest.raises(ValueError, match='same source clock'):
        review(captures[0], captures[1:])
