"""Bounded failure metadata without messages, source text, locals or credentials."""

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
ERROR_TYPES = (
    {
        ("builtins", name)
        for name in (
            "ValueError",
            "TypeError",
            "KeyError",
            "RuntimeError",
            "TimeoutError",
            "OSError",
            "PermissionError",
            "FileNotFoundError",
            "MemoryError",
        )
    }
    | {
        ("app.execution.process", name)
        for name in ("FixtureProcessTimeout", "FixtureProcessFailed", "FixtureProcessProtocolError")
    }
    | {
        ("sqlite3", name)
        for name in ("OperationalError", "DatabaseError", "IntegrityError", "ProgrammingError")
    }
    | {
        ("asyncio.exceptions", "CancelledError"),
        ("app.execution.engine", "ExecutionBlocked"),
    }
)


def failure_details(exc):
    kind = type(exc)
    result = {
        "error_class": kind.__name__
        if (kind.__module__, kind.__name__) in ERROR_TYPES
        else "OTHER_ERROR",
        "frames": [],
    }
    trace = exc.__traceback__
    while trace is not None:
        code = trace.tb_frame.f_code
        try:
            relative = Path(code.co_filename).relative_to(APP_ROOT)
        except ValueError:
            pass
        else:
            # Only installed application locations; never messages or user paths.
            if ".." not in relative.parts:
                result["frames"].append({"file": "app/" + str(relative), "line": trace.tb_lineno})
                result["frames"] = result["frames"][-8:]
        trace = trace.tb_next
    return result
