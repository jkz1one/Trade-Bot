"""Private durable, manually published market fixtures. Never a broker/data client."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from app.domain.models import MarketPacket


class DurableQuoteFeed:
    def __init__(self, path, *, symbols=None, source=None):
        self.path = Path(path).expanduser().resolve()
        if source is not None:
            from app.execution.market_reads import MarketReadPolicy

            source = MarketReadPolicy.model_validate(source).model_dump(mode="json")
            if symbols is None:
                raise ValueError("Source enrollment requires a new feed")
            if len(symbols) > 20 or any(
                not s.isascii() or not s.isalpha() or not s.isupper() or len(s) > 5 for s in symbols
            ):
                raise ValueError("Source enrollment requires a bounded equity universe")
        if symbols is not None:
            if not symbols or len(symbols) != len(set(symbols)):
                raise ValueError("An explicit unique fixture universe is required")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("xb"):
                self.path.chmod(0o600)
            with self._db(write=True) as db:
                db.execute(
                    "CREATE TABLE quote_meta(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE quote_samples(sequence INTEGER PRIMARY KEY, sample_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO quote_meta VALUES(1,?)",
                    (
                        json.dumps(
                            {
                                "schema": "local-fixture-quotes-v1",
                                "feed_id": uuid4().hex,
                                "symbols": list(symbols),
                                **({"source": source} if source is not None else {}),
                            },
                            sort_keys=True,
                        ),
                    ),
                )
        with self._db() as db:
            meta = self._meta(db)
        self.feed_id, self.symbols = meta["feed_id"], meta["symbols"]
        self.source = meta.get("source")

    @contextmanager
    def _db(self, *, write=False):
        db = sqlite3.connect(
            "file:" + quote(str(self.path)) + ("?mode=rw" if write else "?mode=ro"),
            uri=True,
            timeout=0.1,
            isolation_level=None,
        )
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _meta(db):
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != {"quote_meta", "quote_samples"}:
            raise ValueError("Not a local fixture quote feed")
        meta = json.loads(db.execute("SELECT payload FROM quote_meta WHERE id=1").fetchone()[0])
        if meta["schema"] != "local-fixture-quotes-v1":
            raise ValueError("Unknown quote feed schema")
        return meta

    def _binding(self, db):
        meta = self._meta(db)
        if (
            meta["feed_id"] != self.feed_id
            or meta["symbols"] != self.symbols
            or meta.get("source") != self.source
        ):
            raise ValueError("Fixture quote feed identity changed")

    def _validate_packet(self, packet):
        packet = MarketPacket.model_validate(packet.model_dump())
        stamps = [packet.as_of, *(c.quote.timestamp for c in packet.candidates)]
        symbols = [c.quote.symbol for c in packet.candidates]
        if (
            any(t.tzinfo is None or t.utcoffset() is None for t in stamps)
            or len(symbols) != len(set(symbols))
            or set(symbols) - set(self.symbols)
        ):
            raise ValueError("Invalid fixture quote clock or universe")
        if self.source is not None and (
            set(symbols) != set(self.symbols)
            or packet.account.model_dump()
            != MarketPacket(
                as_of=packet.as_of,
                account={"equity": 0, "cash": 0, "buying_power": 0, "high_watermark": 0},
                candidates=[],
            ).account.model_dump()
            or packet.recent_lessons
            or packet.session_context is not None
        ):
            raise ValueError("Sourced quotes require a complete universe and no account authority")
        return packet

    def publish(self, sample_id, packet, *, source=None):
        if source != self.source:
            raise ValueError("Quote publisher source does not match the frozen feed")
        if not isinstance(sample_id, str) or not sample_id.strip() or len(sample_id) > 128:
            raise ValueError("A bounded stable quote sample identity is required")
        packet = self._validate_packet(packet)
        payload = packet.model_dump_json()
        if len(payload.encode()) > 256 * 1024:
            raise ValueError("Fixture market packet too large")
        with self._db(write=True) as db:
            self._binding(db)
            old = db.execute(
                "SELECT sequence,payload FROM quote_samples WHERE sample_id=?", (sample_id,)
            ).fetchone()
            if old:
                if old["payload"] != payload:
                    raise ValueError("QUOTE_SAMPLE_CONTENT_CONFLICT")
                return old["sequence"]
            latest = db.execute(
                "SELECT payload FROM quote_samples ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if latest:
                previous = MarketPacket.model_validate_json(latest[0])
                prior = {c.quote.symbol: c.quote.timestamp for c in previous.candidates}
                if packet.as_of < previous.as_of or any(
                    c.quote.timestamp < prior.get(c.quote.symbol, c.quote.timestamp)
                    for c in packet.candidates
                ):
                    raise ValueError("QUOTE_SAMPLE_TIME_REGRESSION")
            return db.execute(
                "INSERT INTO quote_samples(sample_id,payload) VALUES(?,?)", (sample_id, payload)
            ).lastrowid

    def latest(self):
        with self._db() as db:
            self._binding(db)
            row = db.execute(
                "SELECT sequence,CASE WHEN length(CAST(payload AS BLOB))<=262144 THEN payload ELSE NULL END AS payload FROM quote_samples ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if row is None:
                raise ValueError("FIXTURE_QUOTES_UNAVAILABLE")
            if row["payload"] is None:
                raise ValueError("Fixture market packet too large")
            return row["sequence"], self._validate_packet(
                MarketPacket.model_validate_json(row["payload"])
            )
