"""Installed, offline PAPER acceptance drill; no deployment or trading authority."""

import argparse
import hashlib
import html
import json
import os
import signal
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHASES = {
    "runtime-recovery": ["test_option_runtime.py", "test_option_operator.py"],
    "shared-entry": [
        "test_option_shared_strategy.py",
        "test_option_swing_lifecycle.py",
        "test_option_swing_quotes.py",
        "test_option_swing_targets.py",
        "-k",
        "not enrolled_native_abcd",
    ],
    "observer": ["test_option_observer.py", "test_option_dashboard.py"],
    "accounting": [
        (
            "test_option_swing_lifecycle.py::"
            "test_enrolled_native_abcd_replay_retains_independent_accounts_and_every_cost"
            "[observed-lifecycle-v3]"
        )
    ],
}
STATES = ("populated", "empty", "unavailable", "stale", "halted", "unknown", "long-text", "hold")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def manifest(root, paths):
    result = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Regular source files required")
        result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def application_manifest(root):
    return manifest(
        root, (p for p in (root / "app").rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    )


def application_digest(files):
    return digest(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())


def command(argv, cwd, log, *, timeout=600):
    # Fixture workers never inherit provider/model credentials from the operator shell.
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    with log.open("x") as stream:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return process.wait(timeout=timeout)
        except BaseException:
            # Bound and reap this test process group, including its fixture children.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    continue
                if sig == signal.SIGTERM:
                    # A parent may exit while a child remains in its process group.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                break
            raise


def release(output, name):
    log = output / (name + ".json")
    code = command(
        [sys.executable, "-I", "-m", "app.options.runtime_cli", "release"], output, log, timeout=30
    )
    data = json.loads(log.read_text())
    if code or data.get("status") != "VERIFIED_FILES":
        raise ValueError("Installed release identity unavailable; see " + log.name)
    return data


def counts(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("Completed JUnit summary required")
    result = {
        key: sum(int(s.attrib[key]) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    if result["tests"] <= 0 or any(result[k] for k in ("failures", "errors", "skipped")):
        raise ValueError("All selected tests must finish without failure, error or skip")
    return result


def save(output, report):
    temporary = output / "report.pending"
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(output / "report.json")
    stages = "".join(
        f'<li>{html.escape(name)}: {html.escape(item["status"])} <a href="{name}.log">log</a></li>'
        for name, item in report["phases"].items()
    )
    views = (
        "".join(
            f'<li>{name}: <a href="dashboard/{name}-desktop.html">desktop</a> · '
            f'<a href="dashboard/{name}-mobile.html">mobile</a></li>'
            for name in STATES
        )
        if report.get("dashboard") == "GENERATED"
        else "<li>Not generated</li>"
    )
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Options PAPER test results</title><style>"
        "body{max-width:900px;margin:40px auto;padding:0 20px;background:#0c1422;"
        "color:#dfebf8;font:16px/1.6 system-ui}a{color:#80c5ff}:focus-visible{outline:3px solid #78dfc1}"
        "</style><h1>Options PAPER testing</h1><p>OFFLINE FIXTURES · LIVE DISABLED</p>"
        f"<p>Automated result: <strong>{html.escape(report['status'])}</strong></p>"
        '<p><a href="report.json">Machine-readable evidence</a></p>'
        f"<h2>Automated checks</h2><ul>{stages}</ul><h2>Dashboard review</h2><ul>{views}</ul>"
        "<p>Visual acceptance: PENDING. Inspect clipping, long text, chart labels, "
        "contrast, tab focus and expanded details at both widths. Save screenshots and findings. "
        "Static links to family filters, pagination and API require the authenticated observer; "
        "they are not simulated here.</p><p>These results do not approve real data, authentic "
        "AI usage, host deployment, profitability or LIVE trading. No trader is attached.</p></html>"
    )


def run_tests(output, name, selection):
    copied = output / "tests"
    args = [
        "-c",
        "/dev/null",
        "-p",
        "anyio.pytest_plugin",
        "-q",
        "-W",
        "error",
        "--junitxml=" + name + ".xml",
        "--basetemp=" + str(output / (name + "-state")),
        *selection,
    ]
    bootstrap = (
        "import sys; from pathlib import Path; "
        "sys.path[:0]=[str(Path.cwd().parent),str(Path.cwd())]; import pytest; "
        "raise SystemExit(pytest.main(" + repr(args) + "))"
    )
    code = command([sys.executable, "-I", "-c", bootstrap], copied, output / (name + ".log"))
    if code:
        raise ValueError(name + " failed; see its log")
    return counts(copied / (name + ".xml"))


def run(output, wheel_sha256):
    if not output.is_absolute() or output.resolve().is_relative_to(ROOT):
        raise ValueError("Choose an absolute new output directory outside the checkout")
    output.mkdir(mode=0o700)  # Never adopt or overwrite previous results.
    report = {
        "version": "options-test-kit-v1",
        "status": "RUNNING",
        "phases": {},
        "visual_acceptance": "PENDING",
        "provider_acceptance": "PENDING",
        "host_acceptance": "PENDING",
        "execution_authority": False,
        "live_enabled": False,
    }
    save(output, report)
    try:
        files = application_manifest(ROOT)
        identity = release(output, "release-before")
        if (
            identity["application_sha256"] != application_digest(files)
            or identity["wheel_sha256"] != wheel_sha256
        ):
            raise ValueError("Installed application or wheel does not match the reviewed input")
        report["release"] = identity
        report["harness_sha256"] = digest(Path(__file__).read_bytes())
        copied = output / "tests"
        copied.mkdir(mode=0o700)
        for path in sorted((ROOT / "tests").glob("*.py")):
            if path.is_symlink():
                raise ValueError("Regular test sources required")
            (copied / path.name).write_bytes(path.read_bytes())
        report["test_sources"] = manifest(output, copied.glob("*.py"))
        for name, selection in PHASES.items():
            report["phases"][name] = {"status": "RUNNING"}
            save(output, report)
            print(name + ": running", flush=True)
            result = run_tests(output, name, selection)
            report["phases"][name] = {"status": "PASSED", **result}
            save(output, report)
            print(name + ": " + str(result["tests"]) + " passed", flush=True)
        bootstrap = (
            "import sys; from pathlib import Path; "
            "sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'tests')]; "
            "import options_dashboard_examples as drill; "
            "sys.argv=['dashboard','--output',str(Path.cwd()/'dashboard')]; drill.main()"
        )
        if command([sys.executable, "-I", "-c", bootstrap], output, output / "dashboard.log"):
            raise ValueError("Dashboard generation failed; see dashboard.log")
        if not all(
            (output / "dashboard" / f"{s}-{v}.html").is_file()
            for s in STATES
            for v in ("desktop", "mobile")
        ):
            raise ValueError("Complete dashboard review files required")
        report["dashboard"] = "GENERATED"
        after = release(output, "release-after")
        if (
            after["application_sha256"] != identity["application_sha256"]
            or after["wheel_sha256"] != wheel_sha256
            or application_manifest(ROOT) != files
            or manifest(output, copied.glob("*.py")) != report["test_sources"]
        ):
            raise ValueError("Application or test inputs changed during the run")
        report["status"] = "PASSED_OFFLINE_FIXTURES"
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
        ET.ParseError,
        KeyboardInterrupt,
    ) as exc:
        report["status"] = "FAILED" if isinstance(exc, Exception) else "INTERRUPTED"
        report["error"] = type(exc).__name__ + ": " + str(exc)[:300]
        for item in report["phases"].values():
            if item["status"] == "RUNNING":
                item["status"] = report["status"]
        save(output, report)
        print(report["error"], file=sys.stderr)
        return 2
    save(output, report)
    print("PASSED_OFFLINE_FIXTURES; open " + str(output / "index.html"), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel-sha256", required=True)
    args = parser.parse_args()
    if len(args.wheel_sha256) != 64 or any(c not in "0123456789abcdef" for c in args.wheel_sha256):
        parser.error("Lowercase SHA-256 of the independently retained wheel required")
    os.umask(0o077)
    try:
        return run(args.output, args.wheel_sha256)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
