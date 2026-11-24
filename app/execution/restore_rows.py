"""Bounded reuse of canonical v1 row encodings after hashing every current cell.

Only SQLite scalar tuples are serialized, and pickle is never deserialized.
SHA-256 fingerprints identify typed batches, not account authority. A hit reuses
JSON encoding; the original sorted v1 stream still determines the restore hash.
"""

from collections import OrderedDict
import hashlib
import json
import pickle
import sys
from threading import Lock


class RowEncodings:
    def __init__(self, max_bytes=160 * 1024 * 1024, max_entries=2048):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self.values = OrderedDict()
        self.size = 0
        self.scope = None
        self.lock = Lock()

    def select_authority(self, scope):
        with self.lock:
            if self.scope != scope:
                self.values.clear()
                self.size = 0
                self.scope = scope

    def encode(self, rows):
        rows = tuple(tuple(row) for row in rows)
        # SQLite's normal row factory exposes only these scalar types. Reject
        # blobs and custom Python objects before serialization or cache lookup.
        if any(type(value) not in (str, int, float, type(None)) for row in rows for value in row):
            raise TypeError('Unsupported execution journal cell')
        key = hashlib.sha256(pickle.dumps(rows, protocol=5)).digest()
        with self.lock:
            if key in self.values:
                self.values.move_to_end(key)
                return key, self.values[key][0]
        encoded = tuple(json.dumps(list(row), separators=(',', ':')).encode() + b'\n' for row in rows)
        weight = sys.getsizeof(encoded) + sum(map(sys.getsizeof, encoded)) + sys.getsizeof(key) + 256
        if weight <= self.max_bytes and self.max_entries > 0:
            with self.lock:
                if key in self.values:
                    self.values.move_to_end(key)
                    return key, self.values[key][0]
                while self.values and (self.size + weight > self.max_bytes or len(self.values) >= self.max_entries):
                    # Preserve most of an overflowing sequential scan, as in the
                    # scalar cache. Eviction affects speed only, never authority.
                    _, (_, old_weight) = self.values.popitem(last=True)
                    self.size -= old_weight
                self.values[key] = (encoded, weight)
                self.size += weight
        return key, encoded
