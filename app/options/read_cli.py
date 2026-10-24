"""Private headless schema/sample capture. No engine, model or deployment handle."""

import argparse
import asyncio
import json
import os
import stat
from pathlib import Path
from uuid import uuid4

from app.execution.market_reads import private_oauth
from app.options.read_capture import CapturePolicy, CaptureResult, collect
from app.options.read_gateway import CapturePlan, ReadSchemas, encoded


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def private_json(path, limit=1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or not 0 < info.st_size <= limit
        ):
            raise ValueError("Private bounded current-owner JSON required")
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            raise ValueError("JSON exceeds bound")
        result = json.loads(data, object_pairs_hook=_pairs)
        encoded(result)
        return result
    finally:
        os.close(fd)


def _save(fd, payload):
    data = encoded(payload) + b"\n"
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    while data:
        count = os.write(fd, data)
        if count <= 0:
            raise OSError("Capture write failed")
        data = data[count:]
    os.fsync(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for name in ("discover", "capture"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--oauth-file", required=True)
        cmd.add_argument("--output", required=True)
        cmd.add_argument("--timeout-seconds", type=float, default=30)
        if name == "capture":
            cmd.add_argument("--schemas", required=True)
            cmd.add_argument("--schema-sha256", required=True)
            cmd.add_argument("--plan", required=True)
    args = parser.parse_args(argv)
    fd = None
    admission = {
        "capture_id": uuid4().hex,
        "operation": args.operation,
        "status": "INCOMPLETE",
        "execution_authority": False,
        "normalized_data_verified": False,
    }
    try:
        policy = CapturePolicy(oauth_file=args.oauth_file, timeout_seconds=args.timeout_seconds)
        private_oauth(policy.oauth_file)
        schemas, plan = None, None
        if args.operation == "capture":
            artifact = private_json(args.schemas)
            if (
                artifact.get("status") != "COMPLETE"
                or artifact.get("result", {}).get("operation") != "DISCOVER"
            ):
                raise ValueError("Completed discovery artifact required")
            discovery = CaptureResult.model_validate(artifact["result"])
            if discovery.status != "COMPLETE" or discovery.schemas is None:
                raise ValueError("Completed discovery result required")
            schemas = ReadSchemas.model_validate(discovery.schemas.model_dump(warnings=False))
            if schemas.sha256 != args.schema_sha256:
                raise ValueError("Reviewed schema pin mismatch")
            plan = CapturePlan.model_validate(private_json(args.plan, 64 * 1024))
        output = Path(args.output).absolute()
        parent = output.parent
        info = parent.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise ValueError("Existing private current-owner capture directory required")
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        _save(fd, admission)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        result = asyncio.run(collect(policy, schemas=schemas, plan=plan))
        _save(fd, {**admission, "status": result.status, "result": result.model_dump(mode="json")})
        print(
            json.dumps(
                {
                    "capture_id": admission["capture_id"],
                    "status": result.status,
                    "schema_sha256": result.schemas.sha256 if result.schemas else None,
                    "completed_reads": sum(o.get("completed") is True for o in result.observations),
                    "missing_tools": list(result.schemas.missing_tools) if result.schemas else [],
                    "missing_input_schemas": list(result.schemas.missing_input_schemas)
                    if result.schemas
                    else [],
                    "missing_output_schemas": list(result.schemas.missing_output_schemas)
                    if result.schemas
                    else [],
                    "execution_authority": False,
                    "normalized_data_verified": False,
                }
            )
        )
        return 0 if result.status == "COMPLETE" else 1
    except Exception as exc:  # noqa: BLE001 -- never print OAuth, arguments or provider errors
        failure = {**admission, "status": "FAILED", "error_class": type(exc).__name__}
        if fd is not None:
            try:
                _save(fd, failure)
            except OSError:
                failure["artifact_finalized"] = False
        print(json.dumps(failure))
        return 1
    except KeyboardInterrupt:
        print(json.dumps({**admission, "status": "INTERRUPTED"}))
        return 130
    finally:
        if fd is not None:
            os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
