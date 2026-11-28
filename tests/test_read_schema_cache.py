"""Reuse exact schema-definition checks without caching response acceptance."""
import copy

import pytest
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for

from app.options import read_gateway as gateway


def schema():
    return {'type': 'object', 'required': ['price'], 'additionalProperties': False,
            'properties': {'price': {'type': 'integer', 'minimum': 1}}}


def test_repeated_definition_is_checked_once_but_each_payload_is_validated(monkeypatch):
    value = schema()
    value['title'] = 'isolated repeated definition test'
    cls = validator_for(value)
    original = cls.check_schema
    checked = []
    def check(cls, current, *args, **kwargs):
        checked.append(copy.deepcopy(current))
        return original(current, *args, **kwargs)
    monkeypatch.setattr(cls, 'check_schema', classmethod(check))
    first = gateway._validator(value)
    first.validate({'price': 1})
    second = gateway._validator(copy.deepcopy(value))
    assert second is not first
    second.validate({'price': 2})
    for bad in ({'price': '1'}, {}, {'price': 0}, {'price': 2, 'unexpected': True}):
        with pytest.raises(ValidationError):
            gateway._validator(value).validate(bad)
    assert checked == [value]


def test_nested_schema_mutation_cannot_reuse_previous_approval():
    value = schema()
    gateway._validator(value).validate({'price': 1})
    value['properties']['price']['minimum'] = 2
    with pytest.raises(ValidationError):
        gateway._validator(value).validate({'price': 1})
    value['properties']['price']['type'] = 'not-a-json-schema-type'
    with pytest.raises(SchemaError):
        gateway._validator(value)


@pytest.mark.parametrize('reference', ['$ref', '$dynamicRef'])
def test_warm_cache_never_allows_external_schema_references(reference):
    value = schema()
    gateway._validator(value).validate({'price': 1})
    value['properties']['price'][reference] = 'https://invalid.example/schema'
    with pytest.raises(ValueError, match='embedded'):
        gateway._validator(value)


def test_cache_is_bounded_and_oversized_definitions_are_rejected():
    for n in range(40):
        gateway._validator(schema() | {'title': str(n)})
    assert gateway._checked_validator_type.cache_info().currsize <= 32
    with pytest.raises(ValueError, match='bound'):
        gateway._validator(schema() | {'description': 'x' * gateway.MAX_SCHEMA_BYTES})


def test_embedded_reference_still_validates_every_response():
    value = {'$defs': {'price': {'type': 'integer', 'minimum': 1}},
             '$ref': '#/$defs/price'}
    gateway._validator(value).validate(1)
    with pytest.raises(ValidationError):
        gateway._validator(value).validate('1')
