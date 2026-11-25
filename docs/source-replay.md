# S06 fixture replay

S06 submits the [original S04 payload and receipt key](source-schema.md#receipt-contract-for-tickets-15-and-17). Each invocation has its own run ID and attempt number. If the invocation retries internally, the trace also numbers write deliveries. The durable key stays `(v1, 42, S04)` across all these attempts.

## Run and recover

Stage the [fixture runner image](source-runner.md#stage-and-provision) in the isolated disposable source VM. Use the same project and volume for retry. Pause reset for the entire experiment, including any gap between invocations. Reset deletes the receipts that make reconciliation possible.

```bash
# fixture_runner is the Compose helper from the source runner guide.
fixture_runner --attempt 6 run S06
# After a lost result, use a fresh runner with the same S04 input.
fixture_runner --attempt 7 run S06
```

- `outcome` with `status=committed` returns the key and SHA-256 digest of the original committed result. `resolution=receipt` identifies a match to a stored receipt. `resolution=applied` identifies a delivery that found S03, claimed the key, and committed the receipt and the three S04 inserts together. The receipt schema stores the payload identity. The original inserted values are defined by that payload.
- A different digest at the same key produces a `receipt_mismatch` and a nonzero exit. S06 accepts the literal v1 S04 input. The runtime experiment changes only the payment amount in a test child to exercise rejection.
- If the receipt is absent, S06 can deliver the original payload from exact S03. It claims the receipt in a write transaction before checking the predecessor and applying the inserts. A simultaneous claimant waits at PostgreSQL's receipt key; the losing claimant reads a matching digest in a separate statement. A shared transaction advisory lock uses the same key as the sequential runner's exclusive lock, so the two S06 writers can overlap while excluding sequential writes and reset during their write transactions.
- After a driver operational error during delivery, the runner closes the writer and reads from a fresh reader connection. A matching receipt resolves the outcome. An absent receipt permits the next bounded write delivery through the same claim; a late commit still competes on that key. An unavailable receipt lookup, a missing receipt after conflict, or an exhausted write budget produces `status=unknown` and exit 1. The runner uses at most two writes and a fresh lookup after each interrupted delivery. The standard process deadlines are 3 s connect, 5 s statement, 2 s lock, 15 s idle in transaction and 45 s process time with a 2 s kill grace.

## Reproduce the replay experiment

Provision a **separate** verified disposable project, bridge, volume and writer/reader secret files in the [source profile VM](source-profile.md#stage-and-start). Use the [schema bootstrap](source-schema.md#bootstrap-and-role-setup) and sample disk usage with the existing stop thresholds. Keep other scenario writers paused while the experiment controls its own attempts.

```bash
run_id="$(date -u +%Y%m%dT%H%M%SZ)-p01-01"
mkdir -p artifacts
bash tests/integration/source-replay/run.sh "$run_id" "artifacts/$run_id-replay"
```

The harness resets and advances through S03 for each variant. It records ordered JSON snapshots with all business rows, both aggregate rows, exact receipts, differences from the independent oracle and tuple `xmin` observations. It keeps each runner's JSON trace and stderr. Its child process holds the pre-commit or post-commit boundary for up to 8 s through a pipe. The parent sends `SIGKILL` for the two lost-runner variants. For overlap it waits for PostgreSQL to report that the second receipt claim is blocked by the first transaction before releasing it. Separate variants terminate the staged writer backend to test automatic retry and exhaustion, and force a real reader connection failure after an injected post-commit delivery error. All fault hooks live in the test harness.

The harness ends at S04 and has a 120 s process deadline with a 2 s kill grace. Stop the disposable source and remove its bridge rules using the [source stop procedure](source-profile.md#verify-a-clean-restart-and-stop). See [EXP-008](experiments/EXP-008-source-replay.md) for observed results and bounds.
