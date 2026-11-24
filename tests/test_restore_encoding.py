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
    monkeypatch.setattr(restore, "_TEXT_ENCODINGS", restore._TextEncodingCache())
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
        assert b"[" + b"".join(restore._row_tokens(row)) == json.dumps(list(row), separators=(",", ":")).encode()
    with pytest.raises(TypeError):
        restore._row_tokens((b"unsupported",))


def test_cache_eviction_oversized_rows_and_concurrent_size_accounting():
    cache = restore._TextEncodingCache(max_bytes=1024, max_entries=4)
    strings = ["x" * 2000, *map(str, range(10))] * 100
    with ThreadPoolExecutor(max_workers=8) as pool:
        actual = list(pool.map(lambda value: cache.encode(value, b","), strings))
    assert actual == [json.dumps(value).encode() + b"," for value in strings]
    assert cache.size == sum(weight for _, weight in cache.values.values()) <= 1024
    assert len(cache.values) <= 4
    assert all(len(value) < 200 for value, _ in cache.values)


def test_zero_capacity_does_not_change_encoding():
    cache = restore._TextEncodingCache(max_bytes=0)
    assert cache.encode("entry", b"]") == b'"entry"]'
    assert not cache.values and cache.size == 0


def test_another_authority_releases_pinned_history_without_reusing_handles():
    cache = restore._TextEncodingCache(max_entries=2)
    cache.select_authority("first")
    token, handle = cache.tokens("original" * 1024, b"]")
    cache.select_authority("first")
    assert cache.tokens("original" * 1024, b"]") == (token, handle)
    cache.select_authority("second")
    assert not cache.values and cache.size == 0
    assert all(hint is None for hint in cache.recent_long)
    new_token, new_handle = cache.tokens("original" * 1024, b"]")
    assert new_token == token and new_handle != handle
    cache.select_authority("first")
    assert cache.tokens("original" * 1024, b"]")[1] not in (handle, new_handle)


@pytest.mark.parametrize("bounded_by", ["entries", "bytes"])
def test_over_capacity_scans_reuse_encodings_without_skipping_tampered_text(monkeypatch, bounded_by):
    encoded = []
    original = restore.encode_basestring_ascii

    def measured(value):
        encoded.append(value)
        return original(value)

    monkeypatch.setattr(restore, "encode_basestring_ascii", measured)
    values = [f"{i:04d}" * 1024 for i in range(100)]
    probe = restore._TextEncodingCache()
    probe.encode(values[0], b"]")
    cache = restore._TextEncodingCache(
        max_bytes=probe.size * 80 if bounded_by == "bytes" else 192 * 1024 * 1024,
        max_entries=80 if bounded_by == "entries" else 32768,
    )
    for _ in range(3):
        encoded.clear()
        actual = [cache.encode(value, b"]") for value in values]
        assert actual == [json.dumps(value).encode() + b"]" for value in values]
        assert cache.size <= cache.max_bytes
        assert len(cache.values) <= cache.max_entries
    # A sequential LRU cache would encode all 100 values again on every scan.
    assert len(encoded) <= 22
    changed = values[0][:2000] + "different" + values[0][2009:]
    assert cache.encode(changed, b"]") == json.dumps(changed).encode() + b"]"
    assert cache.encode(values[0], b",") == json.dumps(values[0]).encode() + b","


def test_order_includes_delimiters_and_repeated_history_text_is_shared(monkeypatch):
    cache = restore._TextEncodingCache()
    monkeypatch.setattr(restore, "_TEXT_ENCODINGS", cache)
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE execution_scalar(x)")
        db.execute("CREATE TABLE execution_series(id, payload)")
        payload = "same original quote" * 4000
        for i in (1, 10, 100, -1, -11, 0, 1.0, 1.01, -0.0, 1e-9):
            db.execute("INSERT INTO execution_scalar VALUES(?)", (i,))
            db.execute("INSERT INTO execution_series VALUES(?,?)", (i, payload))
        assert restore._digest(db) == legacy_digest(db)
        assert len(cache.values) == 1
        db.execute("UPDATE execution_series SET payload=? WHERE id=10", (payload + "x",))
        assert restore._digest(db) == legacy_digest(db)
        assert len(cache.values) == 2


def test_repeated_full_scan_reuses_sha_state_only_for_exact_rows_and_schema(monkeypatch):
    from types import SimpleNamespace

    hashed = []
    real_sha = hashlib.sha256

    class MeasuredSHA:
        def __init__(self, state=None):
            self.state = real_sha() if state is None else state

        def update(self, value):
            hashed.append(len(value))
            self.state.update(value)

        def copy(self):
            return MeasuredSHA(self.state.copy())

        def hexdigest(self):
            return self.state.hexdigest()

    monkeypatch.setattr(restore, "hashlib", SimpleNamespace(sha256=MeasuredSHA))
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE execution_a(id, quoted)")
        db.execute("CREATE TABLE execution_z(value)")
        original = "x" * 4096 + "@17," + "y" * 4096
        db.executemany("INSERT INTO execution_a VALUES(?,?)",
                       [(2, original), (1, '"@17,"'), (10, 1.0), (0, None)])
        db.execute("INSERT INTO execution_z VALUES(3)")
        before = legacy_digest(db)
        assert restore._digest(db) == before
        hashed.clear()
        # Observe every original row again, with no second pass through SHA.
        assert restore._digest(db) == before
        assert sum(hashed) == 0
        db.execute("UPDATE execution_z SET value=4")
        assert restore._digest(db) == legacy_digest(db) != before
        assert 0 < sum(hashed) < len(original)
        db.execute("UPDATE execution_a SET quoted=? WHERE id=2", (original.replace("17", "18"),))
        assert restore._digest(db) == legacy_digest(db)
        assert sum(hashed) > len(original)
        db.execute("ALTER TABLE execution_z RENAME COLUMN value TO new_value")
        assert restore._digest(db) == legacy_digest(db)
        db.execute("DROP TABLE execution_z")
        assert restore._digest(db) == legacy_digest(db)


def test_compact_text_comparison_survives_eviction_new_database_and_concurrent_checks(monkeypatch):
    monkeypatch.setattr(restore, "_TEXT_ENCODINGS", restore._TextEncodingCache(max_entries=2))
    with sqlite3.connect(":memory:") as a, sqlite3.connect(":memory:") as b:
        for db, value in ((a, "A"), (b, "B")):
            db.execute("CREATE TABLE execution_values (id, value)")
            db.executemany("INSERT INTO execution_values VALUES(?,?)",
                           [(n, (value if n == 2 else str(n)) * 1024) for n in range(4)])
        assert legacy_digest(a) != legacy_digest(b)
        for db in (a, b, a):
            assert restore._digest(db) == legacy_digest(db)
        with restore._prefix_lock:
            assert restore._digest(b) == legacy_digest(b)
        monkeypatch.setattr(restore, "_PREFIX_BYTES", 32)
        for db in (b, a):
            assert restore._digest(db) == legacy_digest(db)
            assert sum(len(schema) + len(rows) for schema, rows, _ in restore._prefixes) <= 32


def test_long_text_hint_checks_entire_value_and_releases_evicted_keys():
    cache = restore._TextEncodingCache(max_entries=1)
    first = "x" * 8192
    changed = first[:100] + "y" + first[101:]
    token, handle = cache.tokens(first, b"]")
    repeated = (first + " ")[:-1]
    assert repeated is not first
    assert cache.tokens(repeated, b"]") == (token, handle)
    changed_token, changed_handle = cache.tokens(changed, b"]")
    assert changed_token != token and changed_handle != handle
    assert changed_token == json.dumps(changed).encode() + b"]"
    cache.encode("evict", b",")
    assert all(key is None for key in cache.recent_long)
    assert cache.tokens(first, b"]")[1] != handle


def test_overlapping_scans_compare_their_own_database_snapshot(tmp_path, monkeypatch):
    from threading import Event

    paths = [tmp_path / "first.db", tmp_path / "second.db"]
    expected = []
    for path, label in zip(paths, ("first", "second"), strict=True):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE execution_a(id,value)")
            db.execute("INSERT INTO execution_a VALUES(1,?)", ("same" * 2048,))
            db.execute("INSERT INTO execution_a VALUES(2,?)", (label,))
            expected.append(legacy_digest(db))
            assert restore._digest(db) == expected[-1]

    entered, release = Event(), Event()
    original = restore._row_tokens

    def paused(row, comparison=None):
        if row[1] == "first":
            entered.set()
            assert release.wait(5)
        return original(row, comparison)

    def calculate(path):
        with sqlite3.connect(path) as db:
            return restore._digest(db)

    monkeypatch.setattr(restore, "_row_tokens", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(calculate, paths[0])
        try:
            assert entered.wait(3)
            assert pool.submit(calculate, paths[1]).result(timeout=3) == expected[1]
        finally:
            release.set()
        assert first.result(timeout=3) == expected[0]
