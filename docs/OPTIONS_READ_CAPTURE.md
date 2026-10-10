# Private options read evidence acquisition

The first M3 [Degen-to-PAPER path](DEGEN_PAPER.md) accepts normalized fixture
evidence. Actual authenticated option schemas/responses have not been supplied to
this workspace. This installed command acquires that missing evidence using the
existing headless Robinhood MCP connection. It does not initialize an engine, publish
a feed, submit/review an order, invoke a model or install a service.

The code is fixture verified. No authenticated Robinhood call was made during its
implementation. A successful local fixture does not establish provider entitlement,
freshness, exact subject coverage, latency or profitable strategy behavior.

## Fixed capability and schema boundary

`app.options.read_gateway.OptionReadGateway` permits only:

- `get_equity_historicals`, `get_equity_quotes`;
- `get_option_chains`, `get_option_instruments`, `get_option_quotes`,
  `get_option_historicals`.

Robinhood's [official external-agent tool list](https://robinhood.com/us/en/support/articles/trading-with-your-agent/)
lists these read capabilities, checked 2026-10-09 UTC. It does not supply an
authenticated wire-schema acceptance record. Existing legacy/SHADOW firewalls remain
unchanged and continue to reject option reads. This separate capability has no
account-management, positions/orders, watchlist, review, placement, cancellation or
exercise operation. The Trader Agent never receives this gateway.

Discovery invokes `list_tools` once, retains only those six tools' metadata and
records missing tools, input schemas and output schemas. The full normalized retained
metadata has a SHA-256 pin. Discovery can complete while required metadata is absent;
its missing lists must be reviewed. It does not call any market-read tool.

Capture rediscoveries must match the explicitly supplied reviewed pin. Every planned
call is checked before the first market request. Missing input schema, contradictory
read-only annotations, schema drift and invalid arguments block the batch. JSON
Schema validation uses the supported validator and an explicit offline reference
registry; only embedded references are accepted. No remote schema fetch is allowed.
See [jsonschema reference behavior](https://python-jsonschema.readthedocs.io/en/stable/referencing/).
`jsonschema` is now an explicit dependency, already required by the MCP SDK.

Responses retain the raw MCP envelope privately. Tool errors, invalid error flags,
oversized samples and failed advertised structured-output validation stop collection.
If an output schema is absent, a raw sample may still be acquired for mapping review,
but `output_schema_validated` remains false. Neither JSON Schema shape validation nor
a successful read proves real-time prices, completeness or actual symbol/contract
identity. `execution_authority` and `normalized_data_verified` always remain false.

## Headless native process and private output

`app.options.read_capture.collect` launches the same installed interpreter with
`-I -m app.options.read_worker`. The child receives only PATH/LANG/LC_ALL environment
values and a bounded stdin protocol; it has no engine/venue/model/control handle.
The fixed endpoint is `https://agent.robinhood.com/mcp/trading`. Authorization uses an
explicit existing absolute current-owner mode-0600 regular OAuth file, with bounded
stored tokens/client registration. Missing authorization cannot open a browser or
enroll a new account. Necessary OAuth refresh persistence reuses the existing private
storage implementation; it is unrelated to brokerage orders.

The parent owns a nonblocking capture lease keyed to the OAuth path through child
cleanup. This serializes this capture implementation, not legacy clients, other
machines or the broker. Use exclusively managed credentials with no concurrent
refresh consumer. Do not point this tool at the active deployed experiment's OAuth
file or copy a concurrently refreshed authorization.

Bounds are explicit: at most 256 advertised tools, 128 KiB retained metadata, eight
planned calls, 8 KiB arguments per call, 128 KiB per sample, 512 KiB aggregate samples,
256 KiB request and 1 MiB child output. The collection deadline is at most 30 seconds;
native cleanup can add the existing one-second termination grace. Cancellation,
timeout and oversized output drain/terminate/reap the process. A parent-death/deadline
watcher exits an orphaned child independently. The provider's SDK/event limits can
still reject large results; no unbounded pagination or full-chain retry is performed.

The CLI requires an existing current-owner mode-0700 output directory. Every output
is exclusively created mode 0600 before native collection, with an INCOMPLETE
admission flushed to disk and its parent directory. Existing files and final symlinks
are rejected before provider work. The command updates only that newly admitted
artifact. Completed/failed results are flushed; hard interruption during rewriting
can leave INCOMPLETE or partial JSON. Such artifacts are evidence of interruption,
never usable execution authority. Use a distinct output path after inspection.

Ordinary worker failures retain a successful sample prefix, the attempted failing
call and sanitized exception class/timing. Timeout or hard death can lose the child's
unreturned prefix; they cannot claim completed reads. Console output contains only
capture status, pin, missing metadata, counts and false authority flags. OAuth tokens,
request arguments and raw provider errors/results are never printed. Raw samples and
plan files can contain private account/instrument information and stay outside git.
These local files provide no off-host protection or host-loss recovery proof.

## Operator procedure

Use a separately installed verified wheel and dependencies in Python 3.12, on an
authenticated machine with exclusively managed existing authorization. This is not
a reason to pull/rebuild `/opt/trade-bot` or disturb the deployed SHADOW experiment.
The exact tested wheel digest and installed test results are in
[SLICE2_STATUS.md](SLICE2_STATUS.md).

Choose a new private directory and the actual OAuth **file path**, not token text:

```bash
OPTION_CAPTURE_DIR="$HOME/trade-bot-option-evidence-1"
OPTION_OAUTH_FILE="/absolute/path/to/existing-private-oauth.json"
mkdir -m 700 "$OPTION_CAPTURE_DIR"
python -I -m app.options.read_cli discover \
  --oauth-file "$OPTION_OAUTH_FILE" \
  --output "$OPTION_CAPTURE_DIR/discovery.json"
```

Review `result.schemas` in the private discovery artifact and its missing lists.
Use actual captured `inputSchema` definitions to prepare a current-owner mode-0600
`plan.json`. Its application contract is:

| Field | Meaning |
| --- | --- |
| `purpose` | Exactly `SCHEMA_MAPPING_EVIDENCE` |
| `symbols` | One or two unique declared subjects from SPY/QQQ |
| `instrument_ids` | Up to eight unique reviewed exact quote subjects; required for option quote calls |
| `calls` | One to eight objects, each containing unique `label`, fixed permitted `tool`, and its captured-schema `arguments` object |

The declarations describe the operator's intended sample scope. This acquisition
layer does **not** guess argument field mappings or prove that a response contains
the exact declared universe. That semantic binding is a subsequent mapper/acceptance
gate. No broker argument template or synthetic fallback is supplied here. Request
bounded history/instrument subsets according to the actual schemas. Quote candidates
or the known owned contract only; do not turn capture into automatic all-chain polling.

Copy the reviewed 64-character digest into the command below, then acquire samples:

```bash
python -I -m app.options.read_cli capture \
  --oauth-file "$OPTION_OAUTH_FILE" \
  --schemas "$OPTION_CAPTURE_DIR/discovery.json" \
  --schema-sha256 REVIEWED_64_CHARACTER_DIGEST \
  --plan "$OPTION_CAPTURE_DIR/plan.json" \
  --output "$OPTION_CAPTURE_DIR/samples.json"
```

Exit 0 means the acquisition completed, not trading acceptance. Exit 1 records a
sanitized failure where an admission exists; interrupt exits 130. Inspect the private
artifact rather than retrying automatically. Never paste OAuth/token files into chat.
Schemas and appropriately redacted read samples, with actual timestamp/entitlement/
coverage evidence preserved, are the useful review inputs.

## Next acceptance gate

Use actual discovery and sample artifacts to implement an exact normalized mapper
for completed history, observed Greeks/liquidity, contract metadata, timestamps and
entitlement. Bind candidate-first requests to the frozen symbols/expiry and retained
held instrument, verify exact coverage and measured latency, then connect normalized
publication to Degen and independent fast supervision. Missing metadata must produce
HOLD, not inferred defaults. This capture alone does not close M3 provider acceptance.
The [optional bounded model selector](OPTIONS_MODEL_SELECTION.md) has separate
fixture/native proof; authenticated model acceptance, M4 observer/cohort evaluation
and M5 actual isolated host/alerts/archive/source-host-loss proof remain open. LIVE stays disabled.

## Pinned discovery after the passing host probes

The operator's separate installed release passed 1,815 tests and then all eight
disposable credential-namespace probes; see [the evidence record](SLICE2_STATUS.md).
Reuse that installation. Do not install another wheel, rerun the suite, modify
`/opt/trade-bot`, or start an options trader for schema discovery.

This complete command has its release pins filled in. Its only required input is
the **absolute path to separately managed existing Robinhood OAuth JSON**, entered
at the terminal prompt on the server. Do not enter token text or paste the OAuth
file into chat. The capture must exclusively own refresh use of that authorization.
It rejects the known legacy default file and files within the frozen checkout;
this path check cannot detect every other concurrent client or a copied token.
The operator must establish exclusive management, as required above. If no separate
authorization exists, stop here; this headless command cannot enroll one. Do not
work around that prerequisite with the running experiment's file or token copy.

```bash
bash <<'BASH'
set -euo pipefail
umask 077

tb_dir=/opt/trade-bot-validation/618d464f1cbde622d7c05170a99d50cca97c8ca2
tb_source="$tb_dir/source"
test "$(cat "$tb_dir/exit-code")" = 0
test "$(git -C "$tb_source" rev-parse HEAD)" = 618d464f1cbde622d7c05170a99d50cca97c8ca2
test "$(git -C "$tb_source" rev-parse HEAD^{tree})" = d744b2478862d6c1620728b1d024e49090717744
git -C "$tb_source" diff --exit-code HEAD -- app pyproject.toml \
  requirements-runtime.lock requirements-dev.lock requirements-build.lock

printf 'Use separate exclusively managed authorization, never the frozen experiment file.\n'
read -r -p 'Absolute path to separate Robinhood OAuth JSON (blank to stop): ' tb_oauth < /dev/tty
if test -z "$tb_oauth"; then
  echo 'Blocked: separate authorization is required. No provider call made.'
  exit 1
fi

"$tb_dir/venv/bin/python" -I -B - "$tb_oauth" <<'PY'
import os, sys
from pathlib import Path
from app.execution.market_reads import private_oauth

try:
    supplied = Path(sys.argv[1])
    if not supplied.is_absolute():
        raise ValueError("Absolute path required")
    path = supplied.resolve(strict=True)
    legacy = Path("/root/.trade-bot/robinhood-oauth.json")
    if path.is_relative_to(Path("/opt/trade-bot").resolve()) or path == legacy:
        raise ValueError("Frozen/default experiment authorization forbidden")
    if legacy.exists() and os.path.samefile(path, legacy):
        raise ValueError("Shared authorization inode forbidden")
    private_oauth(str(supplied))
except Exception:
    raise SystemExit("Blocked: private separate authorization prerequisite failed. No provider call made.") from None
PY

tb_run=$(mktemp -d "$tb_dir/options-read-discovery-XXXXXX")
cd /
if "$tb_dir/venv/bin/python" -I -B -m app.options.read_cli discover \
  --oauth-file "$tb_oauth" --output "$tb_run/discovery.json" \
  > "$tb_run/summary.json" 2> "$tb_run/stderr.log"; then
  tb_status=0
else
  tb_status=$?
fi
printf '%s\n' "$tb_status" > "$tb_run/exit-code"
printf 'Exit code: %s\nPrivate evidence: %s\n' "$tb_status" "$tb_run"
cat "$tb_run/summary.json"
exit "$tb_status"
BASH
```

Discovery makes one authenticated tool-list request, not market reads or order
reviews. It retains only the six allowed read tools' metadata; refresh persistence
may update the separate authorization file. The existing 30-second collection and
bounded child-cleanup limits apply. The command starts no service, model or engine.
The console summary is the useful next status input. Retain the private discovery
artifact for schema review; do not paste its neighboring OAuth file. Completed
discovery can still report missing metadata and grants no execution authority.
Sample acquisition needs a reviewed plan built from those actual schemas; no
guessed argument template or automatic next batch is included.
