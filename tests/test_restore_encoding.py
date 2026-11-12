"""Compatibility and bounded concurrent encoding for the retained v1 fence."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.execution import restore


def legacy_digest(db):
    digest = hashlib.sha256()
    for row in db.execute(
        "SELECT type,name,sql FROM main.sqlite_master WHERE name GLOB 'execution_*' "
        "AND type IN ('table','trigger','index') ORDER BY type,name"
    ):
        digest.update(json.dumps(list(row), separators=(",", ":")).encode())
        if row[0] == "table":
            name = row[1].replace('"', '""')
            values = sorted(
                json.dumps(list(r), separators=(",", ":"))
                for r in db.execute(f'SELECT * FROM main."{name}"')
            )
            for value in values:
                digest.update(value.encode())
                digest.update(b"\n")
    return digest.hexdigest()


def test_v1_hash_unchanged_with_warm_cache_schema_changes_and_tampering(monkeypatch):
    monkeypatch.setattr(restore, "_ROW_ENCODINGS", restore._RowEncodingCache())
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE execution_values (a, b)")
        rows = [
            (None, ""),
            (1, "1"),
            (1.0, "é\n\\"),
            (-0.0, "🙂"),
            (2**63 - 1, "\x00"),
            (float("inf"), "tail"),
            ("ab", "c"),
            ("a", "bc"),
            (1, "1"),
        ]
        db.executemany("INSERT INTO execution_values VALUES (?,?)", reversed(rows))
        original = legacy_digest(db)
        for _ in range(3):
            assert restore._digest(db) == original
        db.execute("UPDATE execution_values SET b='changed' WHERE a IS NULL")
        assert restore._digest(db) == legacy_digest(db) != original
        db.execute("CREATE INDEX execution_index ON execution_values(a)")
        assert restore._digest(db) == legacy_digest(db)
        db.execute("DELETE FROM execution_values")
        assert restore._digest(db) == legacy_digest(db) != original


def test_encoding_types_boundaries_and_unicode():
    cache = restore._RowEncodingCache()
    rows = [
        (None,),
        ("",),
        (1,),
        (1.0,),
        ("1",),
        (-0.0,),
        (0.0,),
        ("ab", "c"),
        ("a", "bc"),
        ("é", "\ud800"),
        (float("inf"),),
    ]
    for row in rows * 2:
        assert cache.encode(row) == json.dumps(list(row), separators=(",", ":")).encode()
    with pytest.raises(TypeError):
        cache.encode((b"unsupported",))


def test_cache_eviction_oversized_rows_and_concurrent_size_accounting():
    cache = restore._RowEncodingCache(max_bytes=1024, max_entries=4)
    rows = [("x" * 2000,), *[(str(i),) for i in range(10)]] * 100
    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(cache.encode, rows))
    assert actual == [json.dumps(list(row), separators=(",", ":")).encode() for row in rows]
    assert cache.size == sum(weight for _, weight in cache.values.values()) <= 1024
    assert len(cache.values) <= 4
    assert all(len(v) < 200 for v, _ in cache.values.values())


def test_zero_capacity_does_not_change_encoding():
    cache = restore._RowEncodingCache(max_bytes=0)
    assert cache.encode(("entry",)) == b'["entry"]'
    assert not cache.values and cache.size == 0
