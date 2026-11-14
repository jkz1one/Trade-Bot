"""Fixed, bounded child progress telemetry; never retain stderr text or payloads."""

import os
import time
from dataclasses import dataclass


STAGES = ("IMPORTS", "REQUEST", "VENUE_OPEN", "SNAPSHOT", "ACCEPT", "SERIALIZE", "COMPLETE")
PARENT_PHASES = ("SPAWN", "REQUEST_WRITE", "RESPONSE_READ", "CHILD_EXIT", "RESPONSE_VALIDATE")
MAX_TRACE_BYTES = 1024


class ChildTrace:
    def __init__(self):
        self.started = time.monotonic()
        self.cpu_started = time.process_time()

    def mark(self, stage):
        if stage not in STAGES:
            return
        wall = int((time.monotonic() - self.started) * 1_000_000)
        cpu = int((time.process_time() - self.cpu_started) * 1_000_000)
        try:
            os.write(2, f"OPTION_STAGE {stage} {wall} {cpu}\n".encode("ascii"))
        except OSError:
            # Diagnostics cannot change venue behavior.
            pass


class TraceReader:
    def __init__(self):
        self.records = []
        self.pending = b""
        self.size = 0
        self.invalid = False

    def feed(self, chunk):
        if self.invalid:
            return
        self.size += len(chunk)
        if self.size > MAX_TRACE_BYTES:
            self.reject()
            return
        self.pending += chunk
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            parts = line.split(b" ")
            if (len(parts) != 4 or parts[0] != b"OPTION_STAGE"
                    or parts[1] not in {s.encode("ascii") for s in STAGES}
                    or any(not p.isdigit() or len(p) > 9 for p in parts[2:])):
                self.reject()
                return
            stage = parts[1].decode("ascii")
            wall, cpu = map(int, parts[2:])
            if (len(self.records) >= len(STAGES) or wall > 120_000_000
                    or cpu > 120_000_000
                    or any(r[0] == stage for r in self.records)
                    or (self.records and (wall < self.records[-1][1]
                                          or cpu < self.records[-1][2]))):
                self.reject()
                return
            self.records.append((stage, wall, cpu))
        if len(self.pending) > 80:
            self.reject()

    def reject(self):
        self.invalid = True
        self.records.clear()
        self.pending = b""

    async def drain(self, stream):
        while chunk := await stream.read(4096):
            self.feed(chunk)
        if self.pending:
            self.reject()


@dataclass(frozen=True)
class OptionProcessDiagnostics:
    parent_phase: str
    elapsed_seconds: float
    trace_invalid: bool
    stages: tuple

    def public(self):
        # Revalidate before serializing even though only the fixed parent creates it.
        if (self.parent_phase not in PARENT_PHASES
                or type(self.elapsed_seconds) not in (int, float)
                or not 0 <= self.elapsed_seconds <= 3600
                or type(self.trace_invalid) is not bool
                or type(self.stages) is not tuple
                or len(self.stages) > len(STAGES)):
            return None
        reader = TraceReader()
        for record in self.stages:
            if type(record) is not tuple or len(record) != 3:
                return None
            stage, wall, cpu = record
            if (stage not in STAGES or type(wall) is not int or type(cpu) is not int):
                return None
            reader.feed(f"OPTION_STAGE {stage} {wall} {cpu}\n".encode("ascii"))
        if reader.invalid:
            return None
        return {
            "parent_phase": self.parent_phase,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "child_trace_status": "INVALID" if self.trace_invalid else
                                  "OBSERVED" if self.stages else "NOT_OBSERVED",
            "child_stages": [
                {"stage": stage, "elapsed_seconds": round(wall / 1_000_000, 6),
                 "cpu_seconds": round(cpu / 1_000_000, 6)}
                for stage, wall, cpu in self.stages
            ],
        }
