"""Inventory discovers metadata without admitting or calling additional tools."""
import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from test_option_read_capture import Client, metadata, request, plan, oauth
from app.options.capability_inventory import build, summary
from app.options.read_gateway import OptionReadGateway, READ_TOOLS
from app.options import read_worker, read_capture, read_cli


def extras():
    return [{"name": "get_equity_news", "annotations": {"readOnlyHint": True},
             "inputSchema": {"type": "object", "properties": {"symbols": {"type": "array"}}},
             "outputSchema": {"type": "object", "properties": {"news": {"type": "array",
                 "items": {"properties": {"published_at": {"type": "string"}}}}}}},
            {"name": "get_equity_tradability", "annotations": {"readOnlyHint": True}},
            {"name": "place_equity_order", "annotations": {"readOnlyHint": False}},
            {"name": "get_other_quote", "annotations": {"readOnlyHint": True},
             "outputSchema": {"properties": {"bid_size": {"type": "integer"},
                                              "ask_size": {"type": "integer"}}}}]


def test_inventory_keeps_six_tool_pin_and_never_calls_extra_tools():
    client = Client(metadata() + extras())
    gateway = OptionReadGateway(client)
    original = asyncio.run(gateway.discover())
    assert gateway.inventory is None
    current = asyncio.run(gateway.discover(include_inventory=True))
    assert original.sha256 == current.sha256 and set(current.tools) == READ_TOOLS
    assert not client.calls
    result = summary(gateway.inventory)
    assert not result["additional_tools_enabled"] and not result["execution_authority"]
    assert result["market_tool_calls"] == 0
    news = result["candidate_capabilities"]["news_events_and_catalysts"]
    assert news[0]["name"] == "get_equity_news"
    assert "news[].published_at" in news[0]["output_fields"]
    assert any(t['name'] == 'get_other_quote' for t in result['candidate_capabilities']['stock_quotes_and_sizes'])
    assert any(t['name'] == 'place_equity_order' and t['read_only_hint'] is False for t in result['tool_index'])
    assert 'get_equity_news' not in current.tools


def test_worker_inventory_only_lists_metadata(tmp_path, monkeypatch):
    client = Client(metadata() + extras())
    @asynccontextmanager
    async def connected():
        yield client
    class Connection:
        client = staticmethod(connected)
    monkeypatch.setattr(read_worker, 'connection', lambda _: Connection())
    req = request(tmp_path).model_copy(update={'include_inventory': True})
    result = asyncio.run(read_worker.collect(req))
    assert result.status == 'COMPLETE' and result.inventory['tool_count'] == len(client.tools)
    assert client.discoveries == 1 and not client.calls and not result.observations
    assert 'PRIVATE-TOKEN' not in result.model_dump_json()


def test_inventory_is_opt_in_and_cannot_accompany_capture(tmp_path):
    req = request(tmp_path)
    assert 'include_inventory' not in req.model_dump()
    changed = req.model_dump() | {'operation': 'CAPTURE', 'plan': plan().model_dump(),
                                'include_inventory': True}
    with pytest.raises(ValueError, match='discovery-only'):
        read_capture.CaptureRequest.model_validate(changed)


def test_oversized_metadata_and_refs_remain_explicit_not_absent():
    tool = extras()[0]
    tool['description'] = 'x' * (65 * 1024)
    tool['outputSchema'] = {'$ref': '#/$defs/news'}
    inventory = build([tool], READ_TOOLS)
    entry = inventory['tools'][0]
    assert not entry['schemas_retained'] and 'metadata' not in entry
    assert not entry['output_fields_complete']
    assert summary(inventory)['candidate_capabilities']['news_events_and_catalysts']


@pytest.mark.parametrize('raw', [[{'name':'x'}, {'name':'x'}], [{'name':'bad\nname'}], [None]])
def test_invalid_inventory_rejected(raw):
    with pytest.raises(ValueError):
        build(raw, READ_TOOLS)


def test_cli_saves_inventory_without_echoing_full_metadata(tmp_path, monkeypatch, capsys):
    tmp_path.chmod(0o700)
    credentials = oauth(tmp_path)
    destination = tmp_path / 'inventory.json'
    tools = metadata() + extras()
    tools[-1]['description'] = 'PRIVATE-DESCRIPTION-NOT-FOR-STDOUT'
    async def fake_collect(policy, **kwargs):
        assert kwargs['include_inventory'] and kwargs['plan'] is None
        from app.domain.models import utc_now
        gateway = OptionReadGateway(Client(tools))
        schemas = await gateway.discover(include_inventory=True)
        return read_capture.CaptureResult(
            request_id='a'*32, policy_sha256=read_capture.policy_digest(policy),
            operation='DISCOVER', started_at=utc_now(), collected_at=utc_now(),
            elapsed_seconds=0., status='COMPLETE', schemas=schemas, inventory=gateway.inventory,
        )
    monkeypatch.setattr(read_cli, 'collect', fake_collect)
    assert read_cli.main(['inventory', '--oauth-file', str(credentials), '--output', str(destination)]) == 0
    saved = json.loads(destination.read_text())
    assert saved['operation'] == 'inventory' and saved['result']['inventory']['tool_count'] == len(tools)
    output = capsys.readouterr().out
    assert 'PRIVATE-' not in output and json.loads(output)['completed_reads'] == 0
    assert destination.stat().st_mode & 0o777 == 0o600


def test_inventory_crosses_real_isolated_worker_protocol(tmp_path, monkeypatch):
    from test_option_read_capture import native_connection_script, intercept_native
    script = native_connection_script(tmp_path)
    script.write_text(script.read_text().replace(
        repr(json.dumps(metadata())), repr(json.dumps(metadata() + extras()))
    ))
    children = intercept_native(monkeypatch, script)
    policy = read_capture.CapturePolicy(oauth_file=str(oauth(tmp_path)), timeout_seconds=10)
    result = asyncio.run(read_capture.collect(policy, include_inventory=True))
    assert result.status == 'COMPLETE' and not result.observations
    assert result.inventory['tool_count'] == len(metadata() + extras())
    assert set(result.schemas.tools) == READ_TOOLS
    assert all(child.returncode == 0 for child in children)
