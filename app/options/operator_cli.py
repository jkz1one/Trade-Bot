"""Read reviewed options evidence and submit signed local recovery requests."""

import argparse
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from app.domain.models import utc_now
from app.execution import restore
from app.execution.control_api import _secret
from app.options.observer import OptionObserver
from app.options.operator import binding, sign
from app.options.operator_inbox import private_directory, read, save
from app.options.operator_models import OptionsCommand, SignedOptionsCommand


def review(journal, population_id, key_file, *, now):
    if not Path(key_file).is_absolute():
        raise ValueError("Absolute private operator key required")
    key = bytes.fromhex(_secret(key_file))
    observer = OptionObserver(journal, population_id, clock=lambda: now)
    with observer.read() as db:
        b = binding(db, key, population_id)
        if restore.status(db, restore.authority_path(Path(journal)))["status"] != "VERIFIED":
            raise ValueError("Verified restore authority required")
        evidence = observer._snapshot(db, now, 5, None, "ALL")
        return {
            "version": "options-operator-review-v1",
            "journal_id": b["journal_id"],
            "population_id": population_id,
            "credential_generation": b["generation"],
            "revision": evidence["revision"],
            "observed_at": now.isoformat(),
            "evidence": {
                k: evidence[k]
                for k in (
                    "entry",
                    "account",
                    "supervision",
                    "runtime",
                    "model",
                    "position",
                    "active_orders",
                    "loss_control",
                )
            },
            "execution_authority": False,
            "live_enabled": False,
            "network_calls": False,
        }


def submit(journal, review_file, key_file, action, actor, reason, *, now, ttl=60):
    journal = Path(journal)
    if not journal.is_absolute():
        raise ValueError("Absolute journal required")
    if not Path(review_file).is_absolute() or not Path(key_file).is_absolute():
        raise ValueError("Absolute private review and operator key required")
    if type(ttl) is not int or not 1 <= ttl <= 300:
        raise ValueError("Command lifetime must be 1 through 300 seconds")
    saved = json.loads(read(review_file, 256 * 1024))
    if saved["version"] != "options-operator-review-v1":
        raise ValueError("Explicit options operator review required")
    key = bytes.fromhex(_secret(key_file))
    # Authentication/current binding only; never refresh the operator's reviewed revision.
    current = review(journal, saved["population_id"], key_file, now=now)
    if any(
        saved[k] != current[k] for k in ("journal_id", "population_id", "credential_generation")
    ):
        raise ValueError("Reviewed operator binding changed")
    command = OptionsCommand(
        journal_id=saved["journal_id"],
        population_id=saved["population_id"],
        credential_generation=saved["credential_generation"],
        command_id=uuid4().hex,
        actor=actor,
        action=action,
        reason=reason,
        expected_revision=saved["revision"],
        issued_at=now,
        expires_at=now + timedelta(seconds=ttl),
    )
    inbox = journal.parent / "operator-inbox"
    receipts = journal.parent / "operator-receipts"
    private_directory(inbox)
    private_directory(receipts)
    signed = SignedOptionsCommand(command=command, signature=sign(command, key))
    save(inbox / (command.command_id + ".json"), signed.model_dump(mode="json"))
    return {
        "status": "QUEUED",
        "command_id": command.command_id,
        "receipt_file": str(receipts / (command.command_id + ".json")),
        "execution_authority": False,
        "live_enabled": False,
        "network_calls": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    view = commands.add_parser("review")
    view.add_argument("--journal", required=True)
    view.add_argument("--population-id", required=True)
    view.add_argument("--key-file", required=True)
    view.add_argument("--output", required=True)
    send = commands.add_parser("submit")
    send.add_argument("--journal", required=True)
    send.add_argument("--review-file", required=True)
    send.add_argument("--key-file", required=True)
    send.add_argument(
        "--action", choices=["HALT", "RESUME", "REVOKE_KEY", "RESET_LOSS_LOCK"], required=True
    )
    send.add_argument("--actor", required=True)
    send.add_argument("--reason", required=True)
    send.add_argument("--ttl", type=int, default=60)
    args = parser.parse_args(argv)
    try:
        at = utc_now()
        if args.operation == "review":
            destination = Path(args.output)
            if not destination.is_absolute():
                raise ValueError("Absolute new review artifact required")
            result = review(args.journal, args.population_id, args.key_file, now=at)
            save(destination, result)
        else:
            result = submit(
                args.journal,
                args.review_file,
                args.key_file,
                args.action,
                args.actor,
                args.reason,
                now=at,
                ttl=args.ttl,
            )
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": "OPTIONS_OPERATOR_UNAVAILABLE",
                    "live_enabled": False,
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
