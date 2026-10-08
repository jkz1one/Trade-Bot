"""PAPER indicator input integrity and actual bounded 20-symbol child collection."""

import asyncio
import copy
import json
import os
import sys
from datetime import timedelta, timezone

import pytest

from app.domain.models import utc_now
from app.execution import market_reads
from app.execution.market_reads import MarketReadPolicy, collect_once
from app.execution.market_validation import MAX_HISTORY_BARS, PaperMarketReadGateway
from app.execution.quote_feed import DurableQuoteFeed
from app.robinhood.gateway import UnsafeRobinhoodToolError
from app.robinhood.market import RobinhoodMarketData
from tests.test_execution_market_reads import oauth
from tests.test_execution_rehearsal import NOW
from tests.test_robinhood_market import FakeGateway

SYMBOLS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "XLK",
    "XLF",
    "XLE",
    "XLI",
    "XLV",
    "XLY",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "TSLA",
    "AVGO",
    "JPM",
    "COST",
]
TOOLS = ("get_equity_quotes", "get_equity_tradability", "get_equity_historicals")
PYTHON = os.environ.get("PAPER_MARKET_TEST_PYTHON", sys.executable)


class UniverseClient:
    def __init__(self, *, fault=None, tool="get_equity_historicals", now=NOW):
        self.fake = FakeGateway(now)
        self.fault, self.tool = fault, tool
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        result = await self.fake.call_safe(name, arguments)
        sample = result["structuredContent"]["data"]["results"][0]
        rows = []
        for symbol in reversed(arguments["symbols"]):
            item = copy.deepcopy(sample)
            if name == "get_equity_quotes":
                item["quote"]["symbol"] = item["close"]["symbol"] = symbol
            else:
                item["symbol"] = symbol
            rows.append(item)
        result["structuredContent"]["data"]["results"] = rows
        if name == self.tool:
            if self.fault == "missing":
                rows.pop()
            elif self.fault == "extra":
                rows.append(copy.deepcopy(rows[0]))
            elif self.fault == "duplicate":
                if len(rows) == 1:
                    rows.append(copy.deepcopy(rows[0]))
                else:
                    rows[-1] = copy.deepcopy(rows[0])
            elif self.fault == "foreign":
                identity = rows[0]["quote"] if name == TOOLS[0] else rows[0]
                identity["symbol"] = "WRONG"
            elif self.fault == "null":
                rows[0] = None
            elif self.fault == "error":
                result["isError"] = True
        return result


def collector(client):
    return RobinhoodMarketData(PaperMarketReadGateway(client, "fixture"), clock=lambda: NOW)


@pytest.mark.anyio
async def test_complete_universe_preserves_requested_order_and_single_symbol_history():
    client = UniverseClient()
    candidates = await collector(client).candidates("PRIVATE-ACCOUNT", SYMBOLS, NOW)
    assert [c.quote.symbol for c in candidates] == SYMBOLS
    assert all(c.atr_fraction > 0 and c.realized_vol_fraction > 0 for c in candidates)
    assert len(client.calls) == 23
    assert [len(args["symbols"]) for name, args in client.calls if name == TOOLS[1]] == [10, 10]
    history = [args for name, args in client.calls if name == TOOLS[2]]
    assert [args["symbols"] for args in history] == [[s] for s in SYMBOLS]
    assert len({(args["start_time"], args["end_time"]) for args in history}) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("fault", ("missing", "extra", "duplicate", "foreign", "null", "error"))
async def test_ambiguous_batch_cannot_be_silently_collapsed_or_substituted(tool, fault):
    client = UniverseClient(fault=fault, tool=tool)
    with pytest.raises((ValueError, TypeError)):
        await collector(client).candidates("PRIVATE-ACCOUNT", SYMBOLS, NOW)
    assert client.calls[-1][0] == tool


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault",
    (
        "future",
        "before-window",
        "unordered",
        "duplicate-clock",
        "naive",
        "missing-clock",
        "nan",
        "infinite",
        "zero",
        "negative",
        "high-below-close",
        "low-above-open",
        "negative-volume",
        "fractional-volume",
        "bool-volume",
        "missing-volume",
        "missing-interpolation",
        "interval",
        "bounds",
        "empty",
        "oversized",
        "null-bar",
    ),
)
async def test_bad_history_cannot_supply_risk_or_model_indicators(fault):
    class Client(UniverseClient):
        async def call_tool(self, name, arguments):
            result = await super().call_tool(name, arguments)
            if name == TOOLS[2]:
                row = result["structuredContent"]["data"]["results"][0]
                bars = row["bars"]
                if fault == "future":
                    bars[-1]["begins_at"] = (NOW + timedelta(microseconds=1)).isoformat()
                elif fault == "before-window":
                    bars[0]["begins_at"] = (NOW - timedelta(days=8)).isoformat()
                elif fault == "unordered":
                    bars.reverse()
                elif fault == "duplicate-clock":
                    bars[-1]["begins_at"] = bars[-2]["begins_at"]
                elif fault == "naive":
                    bars[0]["begins_at"] = NOW.replace(tzinfo=None).isoformat()
                elif fault == "missing-clock":
                    del bars[0]["begins_at"]
                elif fault in {"nan", "infinite", "zero", "negative"}:
                    bars[0]["open_price"] = {
                        "nan": "NaN",
                        "infinite": "Infinity",
                        "zero": "0",
                        "negative": "-1",
                    }[fault]
                elif fault == "high-below-close":
                    bars[0]["high_price"] = bars[0]["open_price"]
                elif fault == "low-above-open":
                    bars[0]["low_price"] = bars[0]["close_price"]
                elif fault in {"negative-volume", "fractional-volume", "bool-volume"}:
                    bars[0]["volume"] = {
                        "negative-volume": -1,
                        "fractional-volume": "1.5",
                        "bool-volume": True,
                    }[fault]
                elif fault == "missing-volume":
                    del bars[0]["volume"]
                elif fault == "missing-interpolation":
                    del bars[0]["interpolated"]
                elif fault in {"interval", "bounds"}:
                    row[fault] = "wrong"
                elif fault == "empty":
                    row["bars"] = []
                elif fault == "oversized":
                    row["bars"] = [bars[0]] * (MAX_HISTORY_BARS + 1)
                else:
                    bars[0] = None
            return result

    with pytest.raises((ValueError, TypeError)):
        await collector(Client()).candidates("PRIVATE-ACCOUNT", ["SPY"], NOW)


@pytest.mark.anyio
async def test_timezone_offsets_integer_strings_and_interpolated_bars_remain_valid():
    class Client(UniverseClient):
        async def call_tool(self, name, arguments):
            result = await super().call_tool(name, arguments)
            if name == TOOLS[2]:
                bars = result["structuredContent"]["data"]["results"][0]["bars"]
                for bar in bars:
                    bar["volume"] = str(bar["volume"])
                bars[0]["interpolated"] = True
                bars[-1]["begins_at"] = NOW.astimezone(timezone(timedelta(hours=-4))).isoformat()
            return result

    assert len(await collector(Client()).candidates("PRIVATE-ACCOUNT", ["SPY"], NOW)) == 1


@pytest.mark.anyio
async def test_strict_gateway_keeps_broker_capability_firewall():
    class Client:
        async def call_tool(self, *args):
            raise AssertionError("Forbidden tool reached client")

    with pytest.raises(UnsafeRobinhoodToolError):
        await PaperMarketReadGateway(Client(), "fixture").call_safe("review_equity_order", {})


NATIVE_READER = """import json,sys
from contextlib import asynccontextmanager
from pathlib import Path
from app.execution import market_read_worker
payload = json.loads(Path(sys.argv[1]).read_text())
class Client:
    async def call_tool(self, name, args):
        with open(sys.argv[2], 'a') as calls:
            calls.write(json.dumps({'name':name, 'symbols':args.get('symbols', [])}) + '\\n')
        if name == 'get_accounts':
            return {'structuredContent':{'data':{'accounts':[{
                'account_number':'PRIVATE-ACCOUNT', 'type':'limited_margin',
                'brokerage_account_type':'individual', 'agentic_allowed':True,
                'state':'active', 'deactivated':False, 'permanently_deactivated':False}]}}}
        if name == 'get_equity_historicals':
            return payload['history'][args['symbols'][0]]
        if name == 'get_equity_tradability':
            rows = payload[name]['structuredContent']['data']['results']
            return {'structuredContent':{'data':{'results':[
                row for row in rows if row['symbol'] in args['symbols']]}}}
        return payload[name]
class Connection:
    @asynccontextmanager
    async def client(self):
        yield Client()
market_read_worker.connection = lambda policy: Connection()
raise SystemExit(market_read_worker.main())
"""


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault", (None, "cross-bound-history", "duplicate-quotes", "future-bar", "invalid-ohlc")
)
async def test_native_twenty_symbol_child_publishes_atomically_or_retains_old_sample(
    tmp_path, monkeypatch, fault
):
    client = UniverseClient(now=utc_now())
    payload = {
        TOOLS[0]: await client.call_tool(TOOLS[0], {"symbols": SYMBOLS}),
        TOOLS[1]: await client.call_tool(TOOLS[1], {"symbols": SYMBOLS}),
        "history": {
            symbol: await client.call_tool(TOOLS[2], {"symbols": [symbol]}) for symbol in SYMBOLS
        },
    }
    policy = MarketReadPolicy(oauth_file=str(oauth(tmp_path)))
    feed = DurableQuoteFeed(
        tmp_path / "quotes.db", symbols=SYMBOLS, source=policy.model_dump(mode="json")
    )
    responses, calls = tmp_path / "responses.json", tmp_path / "calls.jsonl"
    responses.write_text(json.dumps(payload))
    processes = []
    real_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        assert args == (sys.executable, "-I", "-m", "app.execution.market_read_worker")
        child = await real_spawn(
            PYTHON, "-I", "-c", NATIVE_READER, str(responses), str(calls), **kwargs
        )
        processes.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)

    def refresh_quotes():
        for row in payload[TOOLS[0]]["structuredContent"]["data"]["results"]:
            for field in ("venue_bid_time", "venue_ask_time", "venue_last_trade_time"):
                row["quote"][field] = utc_now().isoformat()
        responses.write_text(json.dumps(payload))

    refresh_quotes()
    first = await collect_once(feed)
    assert first["candidate_count"] == 20 and first["feed_sequence"] == 1
    before = feed.path.read_bytes()
    saved = feed.latest()
    if fault == "cross-bound-history":
        payload["history"]["SPY"], payload["history"]["QQQ"] = (
            payload["history"]["QQQ"],
            payload["history"]["SPY"],
        )
    elif fault == "duplicate-quotes":
        rows = payload[TOOLS[0]]["structuredContent"]["data"]["results"]
        rows.append(copy.deepcopy(rows[0]))
    elif fault in {"future-bar", "invalid-ohlc"}:
        bars = payload["history"]["SPY"]["structuredContent"]["data"]["results"][0]["bars"]
        if fault == "future-bar":
            bars[-1]["begins_at"] = (utc_now() + timedelta(minutes=5)).isoformat()
        else:
            bars[-1]["low_price"] = "200"
    refresh_quotes()
    if fault:
        with pytest.raises(ValueError, match="process failed"):
            await collect_once(feed)
        assert feed.path.read_bytes() == before and feed.latest() == saved
    else:
        assert (await collect_once(feed))["feed_sequence"] == 2
        operations = [json.loads(line) for line in calls.read_text().splitlines()]
        assert (
            len(operations) == 48
        )  # Per refresh: account + quote + two tradability + 20 histories.
        assert {op["name"] for op in operations} == {"get_accounts", *TOOLS}
        assert [c.quote.symbol for c in feed.latest()[1].candidates] == SYMBOLS
    assert len(processes) == 2 and all(p.returncode is not None for p in processes)
    assert "PRIVATE" not in feed.latest()[1].model_dump_json()
    with market_reads.market_read_lease(feed.path):
        pass
