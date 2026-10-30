#!/usr/bin/env python3
"""Pinned, reviewed first simulation setup and bounded host sessions. Never run implicitly."""

import argparse
import fcntl
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "dashboard_host", Path(__file__).with_name("connected-dashboard-host.py")
)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
STATE = Path("/var/lib/trade-bot-connected")
EXPORTS = Path("/var/lib/trade-bot-dashboard-publish")
AUTH = Path("/var/lib/trade-bot-read-auth")
LOCK = Path("/run/lock/trade-bot-connected-host.lock")
LABEL = "trade-bot.connected-session-v1"
PROFILE_HOME = Path("/etc/trade-bot-connected")
MODEL_SOURCE = Path("/etc/trade-bot/openai_api_key")
MODEL_SOURCE_UID = 10001


def prepare_model_key():
    """Explicit host-only copy; leave the original SHADOW key and permissions intact."""
    if MODEL_SOURCE.resolve() != MODEL_SOURCE:
        raise ValueError("Canonical existing model key required")
    fd = os.open(MODEL_SOURCE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != MODEL_SOURCE_UID
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 1 <= before.st_size <= 513
        ):
            raise ValueError("Private existing SHADOW model key required")
        value = stream.read(514)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or len(value) != before.st_size:
            raise ValueError("Model key changed during copy")
    # Exactly the native model-key format, without loading application dependencies.
    secret = value.removesuffix(b"\n").decode("ascii")
    if not 1 <= len(secret) <= 512 or any(
        c.isspace() or ord(c) < 33 or ord(c) > 126 for c in secret
    ):
        raise ValueError("Single-line existing model key required")
    parent(PROFILE_HOME)
    destination = PROFILE_HOME / "model_key"
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(value)
        output.flush()
        os.fsync(output.fileno())
    fd = os.open(PROFILE_HOME, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return {
        "status": "MODEL_KEY_STAGED",
        "destination": str(destination),
        "source_unchanged": True,
        "model_calls": 0,
    }


def private(path, directory=False):
    path = Path(path)
    info = path.lstat()
    if path.resolve() != path or any(c in str(path) for c in (",", "\n", "\x00")):
        raise ValueError("Canonical mount path required")
    if (
        info.st_uid != 0
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    ):
        raise ValueError("Private root-owned host input required")


def parent(path):
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
    private(path, True)


def image(release):
    item = json.loads(h.docker("image", "inspect", "trade-bot-dashboard:" + release).stdout)[0]
    if "TRADER_RELEASE_SHA=" + release not in item["Config"]["Env"]:
        raise ValueError("Pinned release image required")
    return item["Id"]


def mount(source, target, readonly=True):
    return ["--mount", f"type=bind,src={source},dst={target}" + (",readonly" if readonly else "")]


def session_resources():
    # Runtime, collector and publisher (including children) share this quota.
    # Use up to two available CPUs. A larger quota cannot add a core to a
    # single-CPU host. This is a ceiling, not reserved host capacity.
    available = len(os.sched_getaffinity(0))
    return {"cpus": min(2, available), "available_logical_cpus": available}


def isolation(*, cpus=1):
    return [
        "--init",
        "--read-only",
        "--user",
        "0:0",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "1g",
        "--cpus",
        str(cpus),
        "--pids-limit",
        "128",
        "--tmpfs",
        "/tmp:size=128m,mode=1777",
        "-e",
        "TRADER_LIVE_ENABLED=false",
    ]


def config_mounts(writable=False, *, source=False, exports=False, amend_strategy=False):
    if amend_strategy and not writable:
        raise ValueError("Strategy amendment requires writable state")
    private(STATE, True)
    private(STATE / "config", True)
    args = mount(STATE, "/state", not writable)
    if writable and not amend_strategy:
        args += mount(STATE / "config", "/state/config")
    if amend_strategy:
        # Only the reviewed offline amendment publishes runtime.json/manifest.json.
        # Normal sessions retain the read-only directory overlay. Market policy
        # and discovered schemas remain read-only even during this amendment.
        for name in ("policy.json", "schemas.json"):
            private(STATE / "config" / name)
            args += mount(STATE / "config" / name, "/state/config/" + name)
    if source:
        private(STATE / "owner", True)
        args += mount(STATE / "owner", "/source", not writable)
    if exports:
        private(EXPORTS, True)
        args += mount(EXPORTS, "/exports", not writable)
    return args


def execute(image_id, module, args, mounts, *, copies=False):
    caps = ["--cap-add", "CHOWN", "--cap-add", "DAC_READ_SEARCH"] if copies else []
    result = h.docker(
        "run",
        "--rm",
        "--network",
        "none",
        *isolation(),
        *caps,
        *mounts,
        image_id,
        "python",
        "-I",
        "-W",
        "error",
        "-m",
        module,
        *args,
        timeout=60,
        allow_failure=True,
    )
    if result.returncode:
        # Only fixed public reason codes cross this boundary, never raw stderr.
        try:
            reason = json.loads(result.stdout).get("reason")
        except (ValueError, AttributeError):
            reason = None
        if module == "app.mixed.feed_rollover" and reason in {
            "SESSION_CLOSED", "FEED_ROLLOVER_UNAVAILABLE"
        }:
            raise RuntimeError(reason)
        raise RuntimeError("Host command failed: docker run")
    return json.loads(result.stdout)


def bundle(image_id):
    return execute(
        image_id,
        "app.mixed.host_bundle",
        ["verify", "--directory", "/state/config"],
        config_mounts(),
    )


def secrets(manifest):
    args = []
    for role, path in sorted(manifest["binding"]["secret_files"].items()):
        if role not in ("model", "operator"):
            raise ValueError("Unexpected secret role")
        private(Path(path))
        args += mount(path, "/run/secrets/" + role)
    return args


def owner_args():
    return [
        "--directory",
        "/state/owner",
        "--feed-directory",
        "/state/collector",
        "--settings",
        "/state/config/runtime.json",
        "--policy",
        "/state/config/policy.json",
        "--schemas",
        "/state/config/schemas.json",
    ]


def runtime_args():
    return [
        "--directory",
        "/state/owner",
        "--snapshot-owner",
        "/source",
        "--feed-directory",
        "/state/collector",
        "--policy",
        "/state/config/policy.json",
        "--schemas",
        "/state/config/schemas.json",
        "--snapshot-directory",
        "/exports/connected-v1",
        "--reader-uid",
        "10001",
        "--reader-gid",
        "10001",
    ]


def no_active_session():
    if h.docker("ps", "--filter", "label=" + LABEL, "--format", "{{.ID}}").stdout.strip():
        raise ValueError("A connected session is already running")


def review(image_id, phase, seconds=None, run_id=None, *, resume_flat=False):
    manifest = bundle(image_id)
    no_active_session()
    before = h.workers()
    if phase == "enroll":
        if (EXPORTS / "connected-v1").exists() or (EXPORTS / "connected-v1").is_symlink():
            raise ValueError("Publisher already exists; preserve enrolled state")
        native = execute(
            image_id, "app.mixed.connected_owner", ["review", *owner_args()], config_mounts()
        )
        binding = {"native_review_sha256": native["review_sha256"]}
    else:
        if (
            type(seconds) is not int
            or not 1 <= seconds <= 86400
            or not re.fullmatch("[a-z0-9][a-z0-9-]{0,39}", run_id or "")
        ):
            raise ValueError("Explicit bounded duration and unique session ID required")
        name = "trade-bot-connected-" + run_id
        if h.container(name, missing=True) is not None:
            raise ValueError("Session name already exists; retain evidence and choose a new ID")
        native = execute(
            image_id,
            "app.mixed.connected_runtime",
            ["check", *runtime_args()],
            config_mounts(source=True, exports=True),
            copies=True,
        )
        binding = {
            "owner_state": native["owner_state"],
            "policy_sha256": native["effective_policy_sha256"],
            "snapshot_binding_sha256": native["dashboard_snapshot"]["binding_sha256"],
            "seconds": seconds,
            "container_name": name,
            "resources": session_resources(),
        }
    if resume_flat:
        if phase != "run" or native["owner_state"]["halt_reason"] not in {
            "OPTION_RUNTIME_STOPPED", "OPTION_RUNTIME_FAILED",
        }:
            raise ValueError("Reviewed runtime stop/failure required for flat restart")
        binding["resume_flat_reviewed_revision"] = native["owner_state"]["owner_revision"]
    plan = {
        "version": "connected-host-review-v1",
        "phase": phase,
        "image_id": image_id,
        "bundle_sha256": manifest["review_sha256"],
        "configuration": {
            "population_id": manifest["population_id"],
            "initial_virtual_capital": manifest["initial_virtual_capital"],
            "maximum_plays": manifest["maximum_plays"],
            "families": manifest["families"],
            "model_configured": "model" in manifest["binding"]["secret_files"],
            "operator_configured": "operator" in manifest["binding"]["secret_files"],
        },
        "binding": binding,
        "workers": before,
        "entry_blockers": native["entry_blockers"],
        "degen_option_configuration_ready": native.get("degen_option_configuration_ready", False),
        "degen_option_blockers": native.get("degen_option_blockers", []),
        "trading_ready": False,
        "live_enabled": False,
    }
    if before != h.workers():
        raise ValueError("Existing SHADOW identities changed")
    return plan | {"review_sha256": h.digest(plan)}


def snapshot(image_id):
    parent(EXPORTS)
    # The publisher's own create-only checks retain all previous failure evidence.
    mounts = config_mounts(source=True) + mount(EXPORTS, "/exports", False)
    return execute(
        image_id,
        "app.mixed.dashboard_snapshot",
        [
            "create",
            "--owner",
            "/source",
            "--destination",
            "/exports/connected-v1",
            "--reader-uid",
            "10001",
            "--reader-gid",
            "10001",
        ],
        mounts,
        copies=True,
    )


def apply(plan):
    image_id = plan["image_id"]
    manifest = bundle(image_id)
    if manifest["review_sha256"] != plan["bundle_sha256"]:
        raise ValueError("Bundle changed")
    if plan["phase"] == "enroll":
        result = execute(
            image_id,
            "app.mixed.connected_owner",
            ["enroll", *owner_args(), "--expected-review", plan["binding"]["native_review_sha256"]],
            config_mounts(True) + secrets(manifest),
        )
        snapshot(image_id)
        if plan["workers"] != h.workers():
            raise ValueError("Existing SHADOW identities changed")
        return result | {"dashboard_snapshot_created": True}
    private(AUTH, True)
    private(AUTH / "robinhood-oauth.json")
    private(AUTH / "discovery.json")
    resources = session_resources()
    if plan["binding"]["resources"] != resources:
        raise ValueError("Reviewed session resources changed")
    args = config_mounts(True, source=True, exports=True) + secrets(manifest)
    # OAuth directory is writable only for existing token refresh/read leases.
    # Discovery is protected; gateway exposes only the six fixed market-read tools.
    args += mount(AUTH, "/auth", False) + mount(AUTH / "discovery.json", "/auth/discovery.json")
    name = plan["binding"]["container_name"]
    result = h.docker(
        "run",
        "-d",
        "--name",
        name,
        "--restart",
        "no",
        "--stop-timeout",
        "45",
        "--network",
        "bridge",
        "--label",
        LABEL + "=" + plan["review_sha256"],
        "--log-opt",
        "max-size=10m",
        "--log-opt",
        "max-file=3",
        *isolation(cpus=resources["cpus"]),
        "--cap-add",
        "CHOWN",
        "--cap-add",
        "DAC_READ_SEARCH",
        *args,
        image_id,
        "python",
        "-I",
        "-W",
        "error",
        "-m",
        "app.mixed.connected_runtime",
        "run",
        *runtime_args(),
        "--seconds",
        str(plan["binding"]["seconds"]),
        *(["--resume-flat-reviewed-revision", str(plan["binding"]["resume_flat_reviewed_revision"])]
          if "resume_flat_reviewed_revision" in plan["binding"] else []),
    )
    container_id = result.stdout.strip()
    item = h.container(name)
    if item["Id"] != container_id or item["Image"] != image_id or not item["State"]["Running"]:
        raise RuntimeError("Session did not remain running; inspect retained container")
    if h.workers() != plan["workers"]:
        h.docker("stop", "--time", "45", container_id, timeout=55)
        raise RuntimeError("Existing SHADOW identities changed; new session stopped")
    return {
        "status": "SESSION_STARTED",
        "resources": resources,
        "container_name": name,
        "container_id": container_id,
        "seconds": plan["binding"]["seconds"],
        "automatic_resume": False,
        "trading_ready": False,
        "live_enabled": False,
    }


def run(args, release):
    if args.operation == "prepare-model-key":
        return prepare_model_key()
    if args.operation == "build":
        h.docker(
            "build",
            "-f",
            "Dockerfile.shadow",
            "--build-arg",
            "TRADE_BOT_RELEASE=" + release,
            "-t",
            "trade-bot-dashboard:" + release,
            ".",
            timeout=900,
        )
        return {"status": "IMAGE_BUILT", "image_id": image(release)}
    if args.operation in ("review-strategy-upgrade", "apply-strategy-upgrade"):
        no_active_session()
        image_id = image(release)
        apply_upgrade = args.operation == "apply-strategy-upgrade"
        command = ["apply" if apply_upgrade else "review", "--state", "/state"]
        if apply_upgrade:
            command += ["--expected-review", args.expected_review]
        return execute(image_id, "app.mixed.strategy_upgrade", command,
                       config_mounts(writable=apply_upgrade, amend_strategy=apply_upgrade))
    if args.operation in ("status", "stop"):
        if not re.fullmatch("[a-z0-9][a-z0-9-]{0,39}", args.run_id or ""):
            raise ValueError("Session ID required")
        item = h.container("trade-bot-connected-" + args.run_id)
        if not (item["Config"].get("Labels") or {}).get(LABEL):
            raise ValueError("Not a connected session")
        if args.operation == "stop":
            if item["Id"] != args.expected_container:
                raise ValueError("Exact inspected container ID required")
            h.docker("stop", "--time", "45", item["Id"], timeout=55)
            item = h.container("trade-bot-connected-" + args.run_id)
        return {
            "container_id": item["Id"],
            "state": item["State"],
            "restarts": item["RestartCount"],
            "live_enabled": False,
            "trading_ready": False,
        }
    image_id = image(release)
    if args.operation in ("review-profile", "prepare-profile"):
        private(AUTH / "discovery.json")
        mounts = mount(AUTH / "discovery.json", "/input/schemas.json")
        flags = ["--schemas", "/input/schemas.json"]
        operation = "review"
        if args.operation == "prepare-profile":
            parent(PROFILE_HOME)
            parent(PROFILE_HOME / "profiles")
            mounts += mount(PROFILE_HOME / "profiles", "/profiles", False)
            flags += ["--directory", "/profiles/initial", "--expected-review", args.expected_review]
            operation = "create"
        return execute(image_id, "app.mixed.simulation_profile", [operation, *flags], mounts)
    if args.operation in ("review-config", "prepare"):
        if not args.settings or not args.policy:
            raise ValueError("Supplied native settings and policy required")
        for p in (args.settings, args.policy, AUTH / "discovery.json"):
            private(Path(p))
        mounts = (
            mount(args.settings, "/input/runtime.json")
            + mount(args.policy, "/input/policy.json")
            + mount(AUTH / "discovery.json", "/input/schemas.json")
        )
        flags = [
            "--settings",
            "/input/runtime.json",
            "--policy",
            "/input/policy.json",
            "--schemas",
            "/input/schemas.json",
        ]
        if args.operation == "review-config":
            return execute(image_id, "app.mixed.host_bundle", ["review", *flags], mounts)
        parent(STATE)
        return execute(
            image_id,
            "app.mixed.host_bundle",
            [
                "create",
                *flags,
                "--directory",
                "/state/config",
                "--expected-review",
                args.expected_review,
            ],
            mounts + mount(STATE, "/state", False),
        )
    if args.operation in ("prepare-session", "review-session", "enroll-session"):
        bundle(image_id)
        no_active_session()
        if not args.target_session or not args.next_policy:
            raise ValueError("Explicit target session and next policy path required")
        destination = Path(args.next_policy)
        if not destination.is_absolute():
            raise ValueError("Absolute next policy path required")
        if args.operation == "prepare-session":
            captures = Path(args.capture_directory or "")
            if not captures.is_absolute():
                raise ValueError("Absolute original capture directory required")
            private(captures, True)
            for name in ("contracts.json", "quotes-1.json", "quotes-2.json", "quotes-3.json"):
                private(captures / name)
            parent(destination.parent)
            earnings_flags, earnings_mounts = [], []
            swing_flags, swing_mounts = [], []
            scope_flags, scope_mounts = [], []
            if getattr(args, "scope_binding", None):
                scope_file = Path(args.scope_binding)
                if not scope_file.is_absolute():
                    raise ValueError("Absolute reviewed Scope binding required")
                private(scope_file)
                scope_flags = ["--scope-binding", "/scope/binding.json"]
                scope_mounts = mount(scope_file, "/scope/binding.json")
            if getattr(args, "swing_capture_directory", None):
                swing = Path(args.swing_capture_directory)
                if not swing.is_absolute() or not getattr(args, "observed_swing_history", False):
                    raise ValueError("Absolute Swing captures and explicit observed history required")
                private(swing, True)
                for name in ("contracts.json", "quotes-1.json", "quotes-2.json", "quotes-3.json"):
                    private(swing / name)
                swing_flags = ["--swing-capture-directory", "/swing-captures"]
                swing_mounts = mount(swing, "/swing-captures")
            if getattr(args, "earnings_probe", None):
                earnings = Path(args.earnings_probe)
                if not earnings.is_absolute():
                    raise ValueError("Absolute original earnings probe path required")
                private(earnings)
                earnings_flags = ["--earnings-probe", "/earnings/probe.json"]
                earnings_mounts = mount(earnings, "/earnings/probe.json")
            return execute(image_id, "app.mixed.simulation_catalog", [
                "--policy", "/state/config/policy.json", "--contracts", "/captures/contracts.json",
                "--sample", "/captures/quotes-1.json", "--sample", "/captures/quotes-2.json",
                "--sample", "/captures/quotes-3.json", "--target-session", args.target_session,
                "--output", "/proposal/" + destination.name,
                "--report", "/proposal/" + destination.name + ".review.json",
                *earnings_flags,
                *swing_flags,
                *scope_flags,
                *(["--observed-swing-history"] if getattr(args, "observed_swing_history", False) else []),
            ], config_mounts() + mount(captures, "/captures")
               + mount(destination.parent, "/proposal", False) + earnings_mounts + swing_mounts + scope_mounts)
        private(destination)
        flags = ["apply" if args.operation == "enroll-session" else "review",
                 "--directory", "/state/owner", "--feed-directory", "/state/collector",
                 "--policy", "/state/config/policy.json", "--schemas", "/state/config/schemas.json",
                 "--next-policy", "/proposal/policy.json", "--target-session", args.target_session]
        if args.operation == "enroll-session":
            flags += ["--expected-review", args.expected_review]
        return execute(image_id, "app.mixed.feed_rollover", flags,
                       config_mounts(args.operation == "enroll-session")
                       + mount(destination, "/proposal/policy.json"))
    if args.operation == "snapshot":
        bundle(image_id)
        no_active_session()
        return snapshot(image_id)
    phase = "enroll" if args.operation in ("review-enroll", "enroll") else "run"
    plan = review(image_id, phase, args.seconds, args.run_id, resume_flat=getattr(args, "resume_flat", False))
    if args.operation.startswith("review-"):
        return plan
    if plan["review_sha256"] != args.expected_review:
        raise ValueError("Host review changed")
    if review(image_id, phase, args.seconds, args.run_id, resume_flat=getattr(args, "resume_flat", False)) != plan:
        raise ValueError("Host review changed before action")
    return apply(plan)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "operation",
        choices=(
            "build",
            "review-profile",
            "prepare-profile",
            "prepare-model-key",
            "review-config",
            "review-strategy-upgrade",
            "apply-strategy-upgrade",
            "prepare",
            "review-enroll",
            "enroll",
            "snapshot",
            "prepare-session",
            "review-session",
            "enroll-session",
            "review-run",
            "run",
            "status",
            "stop",
        ),
    )
    for name in ("settings", "policy", "expected-review", "run-id", "expected-container",
                 "capture-directory", "target-session", "next-policy", "earnings-probe", "swing-capture-directory", "scope-binding"):
        p.add_argument("--" + name)
    p.add_argument("--resume-flat", action="store_true")
    p.add_argument("--observed-swing-history", action="store_true")
    p.add_argument("--seconds", type=int)
    a = p.parse_args(argv)
    if a.scope_binding is not None and a.operation != "prepare-session":
        p.error("--scope-binding is only for prepare-session")
    if a.earnings_probe is not None and a.operation != "prepare-session":
        p.error("--earnings-probe is only for prepare-session")
    if a.observed_swing_history and a.operation != "prepare-session":
        p.error("--observed-swing-history is only for prepare-session")
    if a.swing_capture_directory and (a.operation != "prepare-session" or not a.observed_swing_history):
        p.error("--swing-capture-directory requires prepare-session --observed-swing-history")
    if (a.operation in ("prepare-profile", "prepare", "enroll", "run", "enroll-session", "apply-strategy-upgrade")) != (
        a.expected_review is not None
    ):
        p.error("Only prepare-profile/prepare/enroll/run require --expected-review")
    if (a.operation == "stop") != (a.expected_container is not None):
        p.error("Only stop requires --expected-container")
    if a.seconds is not None and a.operation not in ("review-run", "run"):
        p.error("Duration is only for session review/run")
    if a.resume_flat and a.operation not in ("review-run", "run"):
        p.error("--resume-flat requires review-run or run")
    fd = None
    try:
        if os.geteuid() != 0:
            raise ValueError("Root host operator required")
        fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        private(LOCK)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.chdir(Path(__file__).resolve().parents[1])
        if h.command(["git", "status", "--porcelain"]).stdout:
            raise ValueError("Clean release checkout required")
        release = h.command(["git", "rev-parse", "HEAD"]).stdout.strip()
        if not re.fullmatch("[a-f0-9]{40}", release):
            raise ValueError("Pinned release required")
        print(json.dumps(run(a, release), sort_keys=True))
        return 0
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
        h.subprocess.SubprocessError,
    ) as exc:
        reason = (
            str(exc) if type(exc) in (ValueError, RuntimeError) else "HOST_INSPECTION_UNAVAILABLE"
        )
        print(
            json.dumps({"status": "UNAVAILABLE", "reason": reason, "live_enabled": False}),
            file=sys.stderr,
        )
        return 2
    finally:
        if fd is not None:
            os.close(fd)


if __name__ == "__main__":
    raise SystemExit(main())
