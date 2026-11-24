"""Read-only cgroup v2 evidence, separate from sampled process RSS."""

from pathlib import Path


def cgroup_memory(directory=Path('/sys/fs/cgroup')):
    try:
        values = {}
        for name in ('current', 'peak', 'max'):
            raw = (directory / ('memory.' + name)).read_text().strip()
            value = None if raw == 'max' and name == 'max' else int(raw)
            if value is not None and value < 0:
                raise ValueError('Nonnegative memory counter required')
            values[name + '_bytes'] = value
        for name, allowed in (
            ('events', {'low', 'high', 'max', 'oom', 'oom_kill', 'oom_group_kill'}),
            ('stat', {'anon', 'file', 'shmem', 'kernel', 'pagetables', 'sock', 'slab'}),
        ):
            values[name] = {}
            for line in (directory / ('memory.' + name)).read_text().splitlines():
                key, raw = line.split()
                if key in allowed:
                    value = int(raw)
                    if value < 0:
                        raise ValueError('Nonnegative memory counter required')
                    values[name][key] = value
        return {'status': 'OBSERVED', 'scope': 'mounted cgroup v2, including file/tmpfs charges', **values}
    except (OSError, ValueError):
        return {'status': 'UNAVAILABLE'}
