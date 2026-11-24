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

    def encode(self, rows, *, slot=None):
        rows = tuple(tuple(row) for row in rows)
        # SQLite's normal row factory exposes only these scalar types. Reject
        # blobs and custom Python objects before serialization or cache lookup.
        if any(type(value) not in (str, int, float, type(None)) for row in rows for value in row):
            raise TypeError('Unsupported execution journal cell')
        key = hashlib.sha256(pickle.dumps(rows, protocol=5)).digest()
        # A repeatedly updated batch must replace its obsolete encoding rather
        # than occupy another cache entry. The slot is only a retention hint;
        # every hit still requires the fingerprint of all current typed cells.
        identity = ('slot', slot) if slot is not None else ('digest', key)
        with self.lock:
            entry = self.values.get(identity)
            if entry is not None and entry[0] == key:
                self.values.move_to_end(identity)
                return key, entry[1]
        encoded = tuple(json.dumps(list(row), separators=(',', ':')).encode() + b'\n' for row in rows)
        weight = (sys.getsizeof(encoded) + sum(map(sys.getsizeof, encoded))
                  + sys.getsizeof(key) + sys.getsizeof(identity) + 256)
        if slot is not None:
            weight += sys.getsizeof(slot) + sum(map(sys.getsizeof, slot))
        if weight <= self.max_bytes and self.max_entries > 0:
            with self.lock:
                entry = self.values.get(identity)
                if entry is not None and entry[0] == key:
                    self.values.move_to_end(identity)
                    return key, entry[1]
                if entry is not None:
                    self.values.pop(identity)
                    self.size -= entry[2]
                while self.values and (self.size + weight > self.max_bytes or len(self.values) >= self.max_entries):
                    # Preserve most of an overflowing sequential scan, as in the
                    # scalar cache. Eviction affects speed only, never authority.
                    _, (_, _, old_weight) = self.values.popitem(last=True)
                    self.size -= old_weight
                self.values[identity] = (key, encoded, weight)
                self.size += weight
        return key, encoded
