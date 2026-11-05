"""Exact reviewed metadata revisions preserve original evidence and wire checks."""
import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.options.read_gateway import ReadSchemas, same_schema_contract, schema_digest


@pytest.fixture
def description_schemas():
    return ReadSchemas.model_validate_json((Path(__file__).parent / 'fixtures' /
        'robinhood_read_schemas_20261104.json').read_text())


def test_discovery_time_is_retained_but_not_part_of_contract_identity(schemas):
    before = schemas.model_dump_json()
    later = schemas.model_copy(update={'captured_at': schemas.captured_at + timedelta(days=30)})
    original_later = later.model_dump_json()
    assert later != schemas
    assert same_schema_contract(later, schemas)
    assert schemas.model_dump_json() == before
    assert later.model_dump_json() == original_later


def test_changed_schema_with_valid_new_digest_still_rejected(schemas):
    value = schemas.model_dump()
    tool = next(iter(value['tools']))
    value['tools'][tool]['inputSchema']['description'] = 'Changed wire metadata'
    value['sha256'] = schema_digest(value['tools'])
    changed = ReadSchemas.model_validate(value)
    assert not same_schema_contract(changed, schemas)


def test_missing_schema_or_tampered_digest_never_matches(schemas):
    assert not same_schema_contract(None, schemas)
    assert not same_schema_contract(schemas, None)
    with pytest.raises(ValueError):
        same_schema_contract(schemas.model_copy(update={'sha256': '0' * 64}), schemas)


def test_supplied_revision_changes_exactly_one_top_level_description(schemas, description_schemas):
    from app.options.read_mapping import reviewed_schemas
    old, new = schemas.model_dump(), description_schemas.model_dump()
    expected = copy.deepcopy(old['tools'])
    before = expected['get_equity_historicals']['description']
    after = new['tools']['get_equity_historicals']['description']
    assert after.startswith(before + '\n- Only completed bars are returned.')
    expected['get_equity_historicals']['description'] = after
    assert expected == new['tools']
    assert schemas.sha256 != description_schemas.sha256
    assert same_schema_contract(schemas, description_schemas)
    assert same_schema_contract(description_schemas, schemas)
    assert reviewed_schemas(description_schemas) == description_schemas
    assert schemas.model_dump() == old and description_schemas.model_dump() == new


@pytest.mark.parametrize('damage', ['description', 'input', 'output', 'annotation', 'name', 'nested_description'])
def test_unreviewed_metadata_cannot_use_description_exception(schemas, description_schemas, damage):
    from app.options.read_gateway import OptionReadGateway, ReadSample, CapturePlan
    from app.options.read_mapping import reviewed_schemas
    value = description_schemas.model_dump()
    tool = value['tools']['get_equity_historicals']
    if damage in {'input', 'output'}:
        tool[damage + 'Schema']['additionalProperties'] = True
    elif damage == 'annotation':
        tool['annotations']['readOnlyHint'] = False
    elif damage == 'nested_description':
        tool['inputSchema']['description'] = 'Unreviewed nested change'
    else:
        tool[damage] += ' unreviewed'
    value['sha256'] = schema_digest(value['tools'])
    current = ReadSchemas.model_validate(value)
    assert not same_schema_contract(current, schemas)
    assert not same_schema_contract(current, description_schemas)
    with pytest.raises(ValueError, match='Unreviewed'):
        reviewed_schemas(current)
    gateway = OptionReadGateway(None)
    gateway.schemas = current
    call = ReadSample(label='book', tool='get_equity_quotes', arguments={'symbols': ['SPY']})
    with pytest.raises(ValueError, match='schemas changed'):
        gateway.validate_plan(CapturePlan(purpose='SCHEMA_MAPPING_EVIDENCE', symbols=('SPY',),
                                         calls=(call,)), schemas)


@pytest.mark.anyio
@pytest.mark.parametrize('invalid_output', [False, True])
async def test_native_worker_and_parent_accept_reviewed_revision_only(
        tmp_path, schemas, description_schemas, monkeypatch, invalid_output):
    from test_option_read_capture import oauth
    from test_robinhood_read_mapping import envelope, equity
    from app.options import read_capture, read_worker
    from app.options.read_gateway import CapturePlan, ReadSample
    seen = []
    class Client:
        async def list_tools(self):
            return list(description_schemas.tools.values())
        async def call_tool(self, name, arguments):
            seen.append((name, arguments))
            raw = equity('SPY')
            if invalid_output:
                raw['bid_price'] = {'not': 'a price'}
            return envelope([{'quote': raw}])
    @asynccontextmanager
    async def client():
        yield Client()
    monkeypatch.setattr(read_worker, 'connection', lambda _: SimpleNamespace(client=client))
    monkeypatch.setattr(read_capture, '_read', read_worker.collect)
    policy = read_capture.CapturePolicy(oauth_file=str(oauth(tmp_path)), timeout_seconds=5)
    call = ReadSample(label='book', tool='get_equity_quotes', arguments={'symbols': ['SPY']})
    plan = CapturePlan(purpose='SCHEMA_MAPPING_EVIDENCE', symbols=('SPY',), calls=(call,))
    result = await read_capture.collect(policy, schemas=schemas, plan=plan)
    assert result.status == ('FAILED' if invalid_output else 'COMPLETE')
    assert result.schemas.sha256 == description_schemas.sha256
    assert result.plan == plan and len(seen) == 1
    assert result.observations[0]['completed'] is not invalid_output
    assert not result.execution_authority and not result.normalized_data_verified


def test_collector_keeps_enrollment_and_raw_new_digest_across_restart(tmp_path, schemas, description_schemas):
    from test_portfolio_feed import policy, reader
    from test_robinhood_read_mapping import AT, instrument
    from app.mixed.continuous_feed import ContinuousFeed
    from app.options.runtime import read_packet
    p = policy()
    path = tmp_path / 'feed'
    seen = []
    for n in range(2):
        at = AT + timedelta(seconds=n * p.poll_seconds)
        base = reader(at, seen, source_shift=n * p.poll_seconds)
        async def capture(cp, **kwargs):
            result = await base(cp, **kwargs)
            # Synthetic advancing provider clock, retained verbatim by delivery.
            for row in result.observations:
                if row['tool'] == 'get_option_quotes':
                    row['raw']['structuredContent']['data']['results'][0]['quote']['updated_at'] = at.isoformat()
            return result.model_copy(update={'schemas': description_schemas})
        feed = ContinuousFeed(path, p, schemas, create=n == 0)
        try:
            before = feed.db.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall()
            result = asyncio.run(feed.tick(now=at, held=(p.stocks[0], instrument()), reader=capture))
            assert result['status'] == 'DELIVERED', result
            raw = json.loads(feed.db.execute('SELECT raw_json FROM attempts WHERE sequence=?',
                                            (result['sequence'],)).fetchone()[0])
            assert raw['schemas']['sha256'] == description_schemas.sha256
            assert feed.schemas == schemas and feed.policy == p
            assert before == feed.db.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall()
        finally:
            feed.close()
        packet = read_packet(path / 'feed.json')
        assert packet.frame.held_quotes[0].source_at == at
        assert packet.recorded_at == at + timedelta(seconds=2)
        assert packet.frame.underlyings[0].source_at == at
    assert [p.calls[0].tool for p in seen] == ['get_equity_quotes'] * 2
