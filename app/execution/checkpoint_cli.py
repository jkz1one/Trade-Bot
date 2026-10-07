"""Explicit evidence-only backup commands; never initializes or resumes an engine."""

import argparse
import asyncio
import json

from app.execution.checkpoint import export_checkpoint, inspect_checkpoint, stage_checkpoint
from app.execution.checkpoint_transfer import archive_config, download_checkpoint, upload_checkpoint


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--journal", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--timeout", type=float, default=10)
    for name in ("inspect", "stage", "upload", "download"):
        item = commands.add_parser(name)
        if name != "download":
            item.add_argument("--bundle", required=True)
        item.add_argument("--sha256", required=True, help="Independently retained export pin")
        if name in {"stage", "download"}:
            item.add_argument("--output", required=True)
        if name in {"upload", "download"}:
            item.add_argument("--origin", required=True)
            item.add_argument("--token-file", required=True)
            item.add_argument("--ca-file")
            item.add_argument("--timeout", type=float, default=30)
        if name == "upload":
            item.add_argument("--receipt-file", required=True)
            item.add_argument(
                "--retry",
                action="store_true",
                help="Explicit same-ID retry of unconfirmed retention",
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = export_checkpoint(args.journal, args.output, timeout_seconds=args.timeout)
        elif args.command == "inspect":
            result = inspect_checkpoint(args.bundle, expected_sha256=args.sha256)
        elif args.command == "stage":
            result = stage_checkpoint(args.bundle, args.output, expected_sha256=args.sha256)
        else:
            config = archive_config(args.origin, ca_file=args.ca_file, timeout_seconds=args.timeout)
            if args.command == "upload":
                result = asyncio.run(
                    upload_checkpoint(
                        args.bundle,
                        config,
                        expected_sha256=args.sha256,
                        token_file=args.token_file,
                        receipt_file=args.receipt_file,
                        retry=args.retry,
                    )
                )
            else:
                result = asyncio.run(
                    download_checkpoint(
                        args.output, config, expected_sha256=args.sha256, token_file=args.token_file
                    )
                )
    except Exception as exc:  # noqa: BLE001 -- errors never echo credentials or archive bodies
        print(
            json.dumps(
                {"status": "ERROR", "error_class": type(exc).__name__, "execution_authority": False}
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
