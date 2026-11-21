"""Small monotonic measurements stored beside, never inside, market packets."""

import time


class AttemptTimer:
    def __init__(self):
        self.started = self.last = time.monotonic()
        self.phase = 'PREPARE'
        self.phases = {}

    def step(self, phase):
        now = time.monotonic()
        self.phases[self.phase] = self.phases.get(self.phase, 0) + now - self.last
        self.last, self.phase = now, phase

    def finish(self, status, capture=None):
        self.step('COMPLETE')
        return {
            'version': 'collector-attempt-timing-v1',
            'status': status,
            'elapsed_seconds': round(self.last-self.started, 6),
            'phases': {k: round(v, 6) for k, v in self.phases.items()},
            'read_process': capture.model_dump(mode='json') if capture else None,
        }
