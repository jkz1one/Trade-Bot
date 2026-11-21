"""Three pinned read-only SPX calls; bounded independently of order capabilities."""
import hashlib
import time
from datetime import datetime, timedelta

from app.domain.models import utc_now
from app.options.input_probe import PINS, check_response, data_of, index_id
from app.options.read_gateway import _validator, encoded

TOOLS = ('get_indexes', 'get_index_quotes', 'get_index_historicals')


def calls(identity, at):
    return (
        ('get_indexes', {'symbols': 'SPX'}),
        ('get_index_quotes', {'instrument_ids': [identity]}),
        ('get_index_historicals', {'instrument_ids': [identity], 'interval': '5minute',
            'start_time': (at - timedelta(days=1)).isoformat(), 'end_time': at.isoformat()}),
    )


def validate(rows, at, *, complete=False):
    if len(rows) > 3 or (complete and len(rows) != 3):
        raise ValueError('Bounded three-read SPX coverage required')
    identity = index_id(data_of(rows[0])) if rows else None
    if len(rows) > 1 and identity is None:
        raise ValueError('Exact SPX identity required before follow-up')
    expected = dict(calls(identity, at))
    if len({row.get('tool') for row in rows}) != len(rows):
        raise ValueError('Duplicate SPX receipt')
    for row in rows:
        name = row.get('tool')
        arguments = expected.get(name)
        if (name not in TOOLS or row.get('arguments') != arguments
                or row.get('metadata_sha256') != PINS[name]
                or type(row.get('completed')) is not bool
                or (complete and row['completed'] is not True)):
            raise ValueError('SPX read binding changed')
        if row.get('completed'):
            if not at <= datetime.fromisoformat(row['attempted_at']) <= datetime.fromisoformat(row['received_at']):
                raise ValueError('SPX receipt clocks regressed')
            if row.get('output_schema_validated') is not True:
                raise ValueError('SPX output validation missing')


async def run(client, inventory, at, observations):
    reviewed = {}
    # Pin all capabilities before opening any of the three market reads.
    for name in TOOLS:
        found = [x.get('metadata') for x in inventory['tools'] if x['name'] == name]
        if (len(found) != 1 or not isinstance(found[0], dict)
                or hashlib.sha256(encoded(found[0])).hexdigest() != PINS[name]
                or found[0].get('annotations', {}).get('readOnlyHint') is not True):
            raise ValueError('SPX read capability changed')
        reviewed[name] = found[0]
    identity = None
    completed_rows = {}
    for index in (0, 2, 1):
        name, arguments = calls(identity, at)[index]
        _validator(reviewed[name]['inputSchema']).validate(arguments)
        row = {'tool': name, 'arguments': arguments, 'metadata_sha256': PINS[name],
               'attempted_at': utc_now().isoformat(), 'completed': False}
        completed_rows[index] = row
        observations[:] = [completed_rows[k] for k in sorted(completed_rows)]
        tick = time.monotonic()
        try:
            raw = await client.call_tool(name, arguments)
            check_response(raw, reviewed[name], row, observations)
            row.update(raw=raw, completed=True, output_schema_validated=True)
        finally:
            row['received_at'] = utc_now().isoformat()
            row['elapsed_seconds'] = time.monotonic() - tick
        if index == 0:
            identity = index_id(data_of(row))
            if identity is None:
                raise ValueError('Exact non-halted SPX identity unavailable')
    validate(observations, at, complete=True)
