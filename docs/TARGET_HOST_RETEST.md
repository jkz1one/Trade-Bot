# Pinned installed-release retest

Use this after a validation fix, with the exact commit and source tree supplied in
the release handoff. This creates a new validation directory and retains the prior
failed installation and log. It installs no trading service, changes no Caddy or
systemd configuration, and does not touch `/opt/trade-bot`.

The host must already have Python 3.12 venv support. The earlier operator evidence
confirmed that installation now works; this command does not refresh apt indexes
or change the unrelated Caddy package repository.

Replace the first two values with the supplied pins, then paste the entire block.
The run survives disconnects. Installation and tests share one private log and an
exit receipt. No receipt means the run has not established successful completion.

```bash
bash <<'BASH'
set -euo pipefail
umask 077
tb_sha=PINNED_COMMIT
tb_tree=PINNED_SOURCE_TREE
[[ "$tb_sha" =~ ^[0-9a-f]{40}$ && "$tb_tree" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Replace both release pins before running."
  exit 1
}
tb_dir="/opt/trade-bot-validation/$tb_sha"
test ! -e "$tb_dir" || {
  echo "Validation directory already exists; retain its evidence and stop."
  exit 1
}
mkdir -m 700 -p "$tb_dir"
cat > "$tb_dir/verify.sh" <<'VERIFY'
set -euo pipefail
umask 077
tb_sha=$1
tb_tree=$2
tb_dir=$3
trap 'tb_status=$?; printf "%s\n" "$tb_status" > "$tb_dir/exit-code.tmp"; mv "$tb_dir/exit-code.tmp" "$tb_dir/exit-code"' EXIT
printf 'Commit: %s\nSource tree: %s\n' "$tb_sha" "$tb_tree"
git clone --single-branch --branch slice2/robinhood-read-shadow \
  https://github.com/jkz1one/Trade-Bot.git "$tb_dir/source"
git -C "$tb_dir/source" checkout --detach "$tb_sha"
test "$(git -C "$tb_dir/source" rev-parse HEAD)" = "$tb_sha"
test "$(git -C "$tb_dir/source" rev-parse HEAD^{tree})" = "$tb_tree"
python3.12 -m venv "$tb_dir/venv"
cd "$tb_dir/source"
"$tb_dir/venv/bin/python" -I -c 'import sys, ssl; print(sys.version); print(ssl.OPENSSL_VERSION)'
"$tb_dir/venv/bin/pip" install -r requirements-build.lock -r requirements-dev.lock
"$tb_dir/venv/bin/pip" wheel --no-deps --no-build-isolation \
  --wheel-dir "$tb_dir/wheels" .
"$tb_dir/venv/bin/pip" install --no-deps "$tb_dir"/wheels/*.whl
"$tb_dir/venv/bin/pip" check
sha256sum "$tb_dir"/wheels/*.whl
mkdir "$tb_dir/checks"
cp -a tests deploy scripts pyproject.toml "$tb_dir/checks/"
cd "$tb_dir/checks"
"$tb_dir/venv/bin/python" -I -c 'import app; print("Installed application:", app.__file__)'
PYTHONPATH= nice -n 10 "$tb_dir/venv/bin/python" -m pytest \
  -q -W error --tb=short -o pythonpath=
"$tb_dir/venv/bin/python" -I -m app.options.observer_cli --help
echo "Pinned installed-release validation passed. No trading service started."
VERIFY
nohup bash "$tb_dir/verify.sh" "$tb_sha" "$tb_tree" "$tb_dir" \
  > "$tb_dir/output.log" 2>&1 < /dev/null &
printf 'Validation launched. Log: %s/output.log\nReceipt: %s/exit-code\n' "$tb_dir" "$tb_dir"
BASH
```

Inspect the same directory after the run:

```bash
tb_dir=/opt/trade-bot-validation/PINNED_COMMIT
tail -n 60 "$tb_dir/output.log"
if test -f "$tb_dir/exit-code"; then
  printf 'Exit code: '; cat "$tb_dir/exit-code"
else
  echo "No completion receipt yet."
fi
```

Set `tb_dir` in the shell used for inspection to the printed absolute directory;
the launcher runs in its own shell. Exit 0 plus a full passing summary, exact pins,
installed import path, dependency check and CLI help is installed-host test proof.
Exit 1 requires the complete log, not only its final failure list. Missing receipts
after process loss do not imply success. Local logs and wheel files provide no
off-host protection.

Even a passing run does not start an options runner or establish authenticated
market/model acceptance, namespace enforcement, boot behavior, independent alerts,
host-loss recovery, profitability or LIVE readiness. See [host boundaries](PAPER_HOST.md)
and [current evidence](SLICE2_STATUS.md).
