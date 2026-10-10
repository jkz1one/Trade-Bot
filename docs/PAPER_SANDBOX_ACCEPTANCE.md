# Disposable PAPER sandbox integration

The opt-in harness tests reviewed credential restrictions as the service UID on
a real systemd host. It uses harmless dummy files and starts no PAPER application,
creates no trading state, uses no provider credentials and changes no SHADOW service.

## Trusted source and prerequisites

Use Ubuntu 24.04 with systemd PID 1, `/usr/bin/python3`, `/usr/bin/systemctl` and
`/usr/bin/systemd-run`. Root access and a pre-provisioned non-root `tradebot-paper`
user/group are required; the user's primary group must match that group. The
harness never creates accounts, installs dependencies or substitutes root.
Missing prerequisites or changed reviewed unit digests block service admission.

From a fresh verified development checkout, set `PAPER_VERIFIED_COMMIT` to the
exact pushed, reviewed SHA and export only the required source:

```bash
git archive --format=tar --output=paper-sandbox-source.tar "$PAPER_VERIFIED_COMMIT" \
  scripts/paper-sandbox-acceptance.py scripts/paper-sandbox-probe.py deploy/paper
sha256sum paper-sandbox-source.tar
```

Transfer through the operator's existing trusted host-access arrangement. Compare
the hash with the independently retained development-machine hash. Extract into a
new root-owned staging directory such as `/root/paper-sandbox-reviewed`, preserving
`scripts/` and `deploy/paper/`. Inspect the scripts and pinned unit bytes: root runs
trusted staged code. Do not extract into, pull or rebuild `/opt/trade-bot`, change
its image or include credentials/databases in this source archive.

## Run and retain evidence

Run once from the trusted staged copy and retain stdout in a new private report:

```bash
umask 077
sudo /usr/bin/python3 -I -B \
  /root/paper-sandbox-reviewed/scripts/paper-sandbox-acceptance.py --run \
  > paper-sandbox-report.json
```

Retain the exit status. Exit 0 requires all eight cases and confirmed cleanup;
exit 1 means blocked/failed evidence. Without `--run`, the script performs no setup.
Record the tested commit, archive hash, UTC time, host identity, OS/kernel and
systemd version with the report. Keep an independent copy before treating it as
target-host evidence.

The script creates unique `trade-bot-paper-acceptance-<random-id>.service` transient
names and exclusive `/var/lib/trade-bot-paper-acceptance-<random-id>` and
`/etc/trade-bot-paper-acceptance-<random-id>` fixture directories. It installs no unit
file, issues no daemon-reload, enables no service and changes no production unit.
Only its transient names receive stop/reset-failed commands. Dummy files contain
harmless fixture text, never real keys or OAuth state.

## Eight cases and required results

Each role runs with all peers present, then with optional/denied peers absent.
Required operator/sink directories remain present for control/alerts. After the
first observation, the parent creates absent known peers and an unlisted `late`
directory, then requests the second observation from the same running probe.

| Role | Allowed dummy reads when initially present | Allowed dummy writes |
| --- | --- | --- |
| Runtime | Model, market | Market only |
| Control | Operator | None |
| Alerts | Alert sink | None |
| Checkpoint | None | None |

All denied peer reads/writes must fail. Newly created unlisted/denied directories
must stay inaccessible. Absent optional model/market binds must remain absent until
explicit restart; the harness never restarts to discover them. A service-owned
dummy file outside writable population/checkpoint paths must be readable but
unwritable under `ProtectSystem=strict`. The probe must use the dedicated UID/GID
and a mount namespace different from PID 1. Successful reports retain before/after
access matrices, reviewed source-unit digests and the transient unit name. Failure
reports also identify the attempted transient unit for targeted journal inspection;
raw manager stderr and dummy file contents are not printed.

All four source-unit SHA-256 digests are checked before any admission and again per
case. Every `[Service]` directive is retained except command/type and test lifecycle
bounds. Only PAPER state/credential roots map to disposable paths; SHADOW path
blocks remain unchanged. The fixed stdlib probe uses `/usr/bin/python3 -I -B`,
`Type=exec`, `Restart=no`, a 30-second runtime cap and five-second stop allowance.
Original `[Unit]` conditions/dependencies and `[Install]` sections are not installed;
checkpoint's original oneshot/timer behavior is not exercised. There are no supplied
path, command or namespace overrides. Ubuntu documents the
[transient property interface](https://manpages.ubuntu.com/manpages/noble/man1/systemd-run.1.html);
`--no-block` queues startup, so its receipt alone cannot pass these tests.

## Failure and acceptance boundary

Observation waits and manager commands have ten-second client deadlines. Probe work
ends within 25 seconds, with a separate manager runtime cap. A lost/timed-out start
response still retains its submitted name for stop. Normal success/failure stops
the transient unit, confirms inactive/failed state, resets only that failure state
and removes only exclusive dummy directories. Unconfirmed cleanup returns
`PROBE_CLEANUP_BLOCKED` with `retained_transient_unit`, preserves fixtures and starts
no further case. An abrupt harness kill/host failure can also leave unique fixtures;
inspect the matching unit before manual cleanup. No automatic pruning/reuse occurs.

Even eight matching cases report `host_acceptance: UNVERIFIED`,
`execution_authority: false` and `live_enabled: false`. Actual target-host results
provide narrow kernel/service-UID evidence for substituted paths and dummy code.
They do not prove the installed fixed mount topology, real credentials, SHADOW path
denial, all filesystem/network restrictions, cgroup descendants, conditions, leases,
graceful shutdown, failure/restart, boot or timer behavior.

Follow with the installed [host snapshot](PAPER_HOST.md#read-only-host-snapshot-audit)
and actual application lifecycle exercises. Authenticated market/model operation,
independent alerts, archive retention/retrieval and host-loss recovery remain gates.
Local mocked matrices, native probe tests and parser acceptance verify the harness
only. No DigitalOcean kernel result is supplied by this implementation.

## Pinned follow-up after the passing 2026-10-10 installed run

The operator's `618d464f1cbde622d7c05170a99d50cca97c8ca2` installation passed all
1,815 tests, exit 0; see [the retained record](SLICE2_STATUS.md). The following
complete command reuses that verified source directory and needs no application
reinstall. It verifies the pinned source and unchanged probe/unit files, requires
systemd PID 1, provisions only the dedicated non-login account if absent, then runs
the existing eight disposable cases. Existing account/group authority is validated;
no account is retuned. Account provisioning is an explicit operator step outside
the harness, whose prerequisites above remain unchanged.

Run this as root on that same host. It prints a compact result and saves full JSON,
host/kernel/systemd metadata, stderr and an exit receipt in a unique private
directory below the already validated release. The account persists for separate
future provisioning; transient dummy units and their fixtures are cleaned up only
when their termination is confirmed. This does not install/enable/start a production
PAPER trader or change the frozen SHADOW experiment. An abrupt shell/host kill
before the receipt remains incomplete evidence; retain the report and any named
leftover transient unit for inspection.

```bash
bash <<'BASH'
set -euo pipefail
umask 077

tb_dir=/opt/trade-bot-validation/618d464f1cbde622d7c05170a99d50cca97c8ca2
tb_source="$tb_dir/source"
test "$(cat "$tb_dir/exit-code")" = 0
test "$(git -C "$tb_source" rev-parse HEAD)" = 618d464f1cbde622d7c05170a99d50cca97c8ca2
test "$(git -C "$tb_source" rev-parse HEAD^{tree})" = d744b2478862d6c1620728b1d024e49090717744
git -C "$tb_source" diff --exit-code HEAD -- scripts/paper-sandbox-acceptance.py scripts/paper-sandbox-probe.py deploy/paper
test "$(cat /proc/1/comm)" = systemd

if ! /usr/bin/getent passwd tradebot-paper >/dev/null; then
  if /usr/bin/getent group tradebot-paper >/dev/null; then
    /usr/bin/python3 -I -c 'import grp; assert grp.getgrnam("tradebot-paper").gr_gid > 0'
    /usr/sbin/useradd --system --gid tradebot-paper --no-create-home \
      --home-dir /nonexistent --shell /usr/sbin/nologin tradebot-paper
  else
    /usr/sbin/useradd --system --user-group --no-create-home \
      --home-dir /nonexistent --shell /usr/sbin/nologin tradebot-paper
  fi
fi

/usr/bin/python3 -I -c 'import pwd, grp; u=pwd.getpwnam("tradebot-paper"); g=grp.getgrnam("tradebot-paper"); assert u.pw_uid > 0 and g.gr_gid > 0 and u.pw_gid == g.gr_gid, "Dedicated service identity mismatch"'

tb_run=$(mktemp -d "$tb_dir/sandbox-verification-XXXXXX")
{
  echo "Validated release: 618d464f1cbde622d7c05170a99d50cca97c8ca2"
  date -u
  uname -srm
  cat /etc/os-release
  /usr/bin/systemctl --version
} > "$tb_run/host-metadata.txt"

if /usr/bin/python3 -I -B "$tb_source/scripts/paper-sandbox-acceptance.py" --run \
  > "$tb_run/report.json" 2> "$tb_run/stderr.log"; then
  tb_status=0
else
  tb_status=$?
fi
printf "%s\n" "$tb_status" > "$tb_run/exit-code"
printf 'Exit code: %s\nSaved evidence: %s\n' "$tb_status" "$tb_run"

/usr/bin/python3 -I - "$tb_run/report.json" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    report = json.load(stream)
print("Result:", report.get("status"))
print("Cases:", len(report.get("cases", [])))
for case in report.get("cases", []):
    print(case["role"], case["initial_peers"], case["status"],
          "separate namespace:", case.get("separate_mount_namespace"))
for key in ("reason", "current_case", "transient_unit", "retained_transient_unit"):
    if key in report:
        print(key + ":", report[key])
print("Full host acceptance:", report.get("host_acceptance"))
print("LIVE enabled:", report.get("live_enabled"))
PY
exit "$tb_status"
BASH
```

Exit 0 with eight OBSERVED cases supplies narrow credential-namespace proof on
substituted fixture paths. The report deliberately keeps full host acceptance
UNVERIFIED. Installed application/real credential topology, lifecycle/boot,
independent alerts and recovery still need their separate evidence. Send the compact
result and retain the full private report. No actual DigitalOcean probe result has
been supplied at this documentation checkpoint.
