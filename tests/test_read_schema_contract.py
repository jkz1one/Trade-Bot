"""Fresh discovery timestamps do not change an otherwise identical pinned schema."""
from datetime import timedelta

import pytest
from test_robinhood_read_mapping import schemas as schemas  # noqa: PLC0414

from app.options.read_gateway import ReadSchemas, same_schema_contract, schema_digest


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
