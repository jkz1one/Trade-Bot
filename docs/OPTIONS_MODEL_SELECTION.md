# Optional Degen candidate model selection

This **M3 fixture capability** adds tool-less model selection to the separate local
options PAPER owner. Default Degen selection is still deterministic. Model use is
optional and must be frozen in a new, untraded population. No authenticated model
or options provider acceptance, options deployment, broker write or LIVE activation
is evidenced by this module.

## Capability and authority

`app.options.judgment.CandidateChoice` permits only `SELECT`, one supplied candidate
ID and a bounded thesis, or `HOLD` with no ID. It cannot propose contracts, quantity,
price, invalidation, funding, deadlines or recovery actions. The packet contains the
completed scans, exact already admitted candidates, authoritative account evidence
and deterministic limits. Packet values remain evidence, never instructions.

The fixed native `app.options.judgment_worker` counts the exact Responses payload
before at most one generation. Both requests use the same frozen model, prompt,
strict schema and packet, `tools=[]`, `tool_choice="none"` and disabled truncation.
Generation disables storage, background work and streaming. The official API origin
is fixed and SDK retries are disabled. The child's environment carries the model
key only, plus minimal locale/path variables. It receives no broker credential,
OAuth path, journal path, local venue path or order handle. The process protocol
binds request ID, packet hash and frozen configuration hash.

Only one completed final assistant text message is accepted. Refusals, fragments,
tool output, incomplete responses, malformed choices and invented IDs become HOLD.
Returned matching-model usage is retained before choice parsing and charged even
when output is rejected, late or HOLD. Input-count/usage disagreement and token-bound
violations cannot grant entry. Missing usage, wrong model, unbound protocol, failed
child, cancellation or uncertain storage retains an unknown durable attempt and
halts new entries. No invented zero cost, automatic replay or deterministic fallback
follows a failed model attempt. A valid provider ID cannot settle two distinct calls.
Configured rates produce estimates, not proof of actual billing.

The model wait is bounded by the earliest original candidate approval expiry, the
remaining five-minute entry slot and frozen process deadline. Fresh admission runs
**after** cost settlement. It may reduce quantity, but cannot exceed the original
quantity, limit price, entry debit or full-premium funding. The fixed intent keeps
at most the original approval expiry. Waiting for a model never renews permission.
A slow response therefore yields cash HOLD; authenticated latency evidence is
needed before assessing whether this short lease is operationally useful.

`await coordinator.supervise(...)` remains independent of entry/model work. Held
and pending identities come from the journal, and deterministic protective exits
do not require a model call or a readable model key. Accepted local venue orders
remain unfilled until authoritative fill evidence arrives. They are not positions
or profitability proof.

## Explicit opt-in use

Create a separate `OptionExecutionPolicy` with an explicit frozen `CostPolicy`,
reconcile its local venue and assess flat supervision. Before any orders, decisions
or model attempts, construct:

```python
coordinator = DegenCoordinator(
    engine,
    setup_policy,
    contract_selection_policy,
    create=True,
    judgment_limits=JudgmentLimits(
        max_input_tokens=16000,
        max_output_tokens=1024,
        process_timeout_seconds=30,
        request_timeout_seconds=20,
    ),
    key_file=absolute_private_model_key_path,
)
```

The token ceilings' maximum configured charge must fit the per-call reservation.
The model key file must be owned by the current user, mode 0600, a bounded regular
file, and not a symlink. It is read only when eligible entry candidates exist;
construction, stored reports and protective supervision do not read it. Never put
keys in chat, Git, arguments or evidence artifacts. Examples describe API shape,
not an approved trading population, funded bankroll or trading configuration.

Reopen with `create=False`, the same setup/selection/model policies and key path.
Frozen model, prompt/schema hashes, rates, budgets, token/time limits and key path
cannot be retuned by restarting. Existing model-off cohorts keep their exact stored
configuration and do not acquire model behavior. Switching either direction needs
an explicitly separate new population. This is a library API, not an installed
options runtime or a new deployment command.

## Evidence and remaining gates

`tests/test_option_judgment.py` exercises the installed SDK with mocked HTTP
transport, native worker main, original admission ceilings, cost-reduced sizing,
durable HOLD, native failures/reaping, repeated cancellation, independent fast
supervision, returned-evidence preservation through storage failure and actual
owner SIGKILL with interrupted restart. The orphan watcher exits with code 99;
unknown usage remains unresolved and the same opportunity is never retried.
Latest installed-suite and wheel proof is in [SLICE2_STATUS.md](SLICE2_STATUS.md).
All provider responses in these tests are fixtures; no real model call was made.

The next provider gate remains [authenticated schema/sample acquisition](OPTIONS_READ_CAPTURE.md),
then an exact normalized collector for candidate and held-contract evidence.
Authenticated full-universe/read/model latency, real usage/billing and supervised
sessions must be evidenced separately. M4 observer/cohort evaluation, mixed
stock/options ownership and M5 host/namespace/lifecycle/alert/archive/source-loss
acceptance remain open. The old deployed synthetic experiment stays frozen.
See [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md) for the delivery contract.
