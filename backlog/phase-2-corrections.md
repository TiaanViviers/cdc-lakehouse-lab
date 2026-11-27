# Proposed Phase 2 corrective work

**Approved and published.** The maintainer authorized 2.11–2.13 after independent review of [PR #58](https://github.com/TiaanViviers/cdc-lakehouse-lab/pull/58). M2 remains unmet and [2.10 / #47](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/47) remains open.

| Ticket | [Phase 2 milestone](https://github.com/TiaanViviers/cdc-lakehouse-lab/milestone/3) | Initial [board](https://github.com/users/TiaanViviers/projects/3) status |
| --- | --- | --- |
| 2.11 | [#59](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/59) | Ready |
| 2.12 | [#60](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/60) | Ready |
| 2.13 | [#61](https://github.com/TiaanViviers/cdc-lakehouse-lab/issues/61) | Backlog |

The issues and ticket registry record the dependencies. Native GitHub blocked-by links include the two corrective prerequisites of 2.13 and all three corrective prerequisites of 2.10. Phase 3 publication remains pending.
 [Closeout](../docs/phase-2-closeout.md) · [Existing full M2 review](../docs/cdc-gate.md#review-the-full-m2-decision)

Dependency types used here and in Phase 3 are **I** for implementation/interfaces, **R** for runtime evidence needed for acceptance and **G** for a maintainer or research decision. An R dependency can allow offline work before its run. All tickets require dedicated worktrees/branches from updated main, the existing exclusive VM lease, distinct disposable identities, independent evidence and fail-closed isolation and teardown. Assign one owner to reconcile any accepted connector patches that touch shared dispatch/checkpoint paths.

## 2.11 Bound sparse-table feedback without skipping committed changes

**Type:** research, priority:high. **Research:** R03, R04, R05. **Depends:** R 2.7 and 2.9, G corrective scope approval. **Begin:** after approval with offline candidate evaluation and fixture tracing. Review a candidate patch or operating strategy and its invariant before integrated acceptance.

**Objective and scope.** Keep retention bounded during sparse normal activity while preserving every committed effect through restart. Assess a connector fix and bounded operating alternatives. An all-table no-op touch is a diagnostic. Operational dependence on it requires evidence of coverage, idle behavior, safety and overhead. A larger cap, manual slot advance, forced invalidation or periodic resnapshot cannot count as successful sparse operation. Source-atomic Bronze publication is outside scope.

**Acceptance and evidence.**

- Reproduce EXP-020 on the current pin. Add a bounded sustained run with at least three committed/checkpoint epochs with a mapped table idle, a silent interval and a second burst. Predeclare the duration, workload, retained span, allocated WAL, headroom alert and stop thresholds within existing limits. Require measurable appropriate feedback and bounded steady-state retention.
- Attribute source positions, durable per-table results and feedback separately. Require successive exact all-table reads including real updates/deletes and same-slot recovery. Test a bounded fault near apply/checkpoint/feedback and show feedback cannot advance beyond recoverable effects at the tested boundary. If the intended crash window is missed, record it and review the invariant before considering acceptance.
- Retain before/after WAL and disk, cgroups, exact diffs, pin/configuration, bounded commands and lost-slot procedure. A negative result can complete the investigation while leaving M2 unmet.

**Ownership and contract.** Own proposed `tests/integration/cdc-sparse/` and report. Reuse `scripts/cdc/wal/`, the parity adapter and gate harness. Hand off invariant, candidate patch/options, pin and measured evidence to 2.13.

## 2.12 Correct convergence across the initial COPY boundary

**Type:** bug, priority:high. **Research:** R02–R05. **Depends:** R 2.6 and 2.9, G corrective scope approval. **Begin:** after approval. Diagnose on the pinned writer independently of 2.11.

**Objective and scope.** Explain and close the witnessed concurrent COPY miss. Preserve stock PG16, the fixture and its independent expectations. Held onboarding is a control and an isolated research setup. The concurrent COPY criterion still requires a witnessed positive result.

**Acceptance and evidence.**

- Attribute source XID, decoded change and COMMIT/END LSN, COPY repeatable-read view and consistent point, persistent slot start, mapping/queue generation and routing, skip or replay decisions. Use bounded redacted instrumentation or an approved separate disposable decoder slot. Compare previous failure and positive controls, and record remaining uncertainty around the cause.
- Require at least three fresh positive holds with the same COPY backend and temporary slot across the S01 commit. Test boundary variations around slot creation and COPY handoff. Confirm exact source S01 before release, target exact S01 by the existing deadline, full item 102 update and deletion back to exact S00, with no reseed or direct target repair. Verify a held four-table control, slot release and clean teardown. Preserve failed or inconclusive attempts.
- Hand off the reversible build/configuration, run identities, exact diffs, diagnostic traces and cleanup evidence. If no candidate passes, preserve the blocked outcome.

**Ownership and contract.** Own COPY-overlap changes in `tests/integration/cdc-baseline/`, diagnostics and report. Preserve the held baseline/oracle interfaces for 2.13 and Phase 3. Coordinate shared DuckPipe changes with 2.11 via the integration owner.

## 2.13 Reverify M2 on the integrated correction

**Type:** research, priority:high. **Research:** R01–R06, R08, R09, R13, R16. **Depends:** I 2.11 and 2.12 candidates, R 2.11 and 2.12 positive results, G reviewed compatible pin and controls. **Begin:** plan the evidence matrix after approval. Run after the candidates integrate with updated main and one consistent artifact set.

**Objective and scope.** Apply the existing full M2 review to the corrected candidate. The maintainer decides M2 acceptance and transition.

**Acceptance and evidence.**

- Repeat two fresh paired projects with exact S00–S05, rollback/deleted-key exclusion, same-slot recovery and replacement, sparse budget checks and checked teardown. Repeat the separate witnessed COPY acceptance. Review source-only, lifecycle, auth/isolation, local physical persistence, abrupt/loss and visibility controls at their documented boundaries on the same revision and effective pins. Preserve command output, fingerprints, exact rows, status/logs and resource bounds.
- Update gate evidence, research statuses, pins and runbook. Preserve the paired command's limited verdict. Record any failed, missing or inconclusive mandatory outcome as an unmet M2 and seek the maintainer's decision.

**Ownership and contract.** Own `tests/integration/cdc-gate/` integration if required and final experiment/verification docs. Reuse existing controls with their owners' review. Hand off to the original 2.10 / #47, which remains the last item to complete.

```text
approval → 2.11 sparse feedback ─┐
        └→ 2.12 COPY convergence ┴→ integrated pin → 2.13 full re-gate → M2 decision → 2.10 later handover
```

Investigate 2.11 and 2.12 in parallel with separate files. Serialize their narrow VM runs and reserve the guest for final integrated acceptance. An upstream fix or operating strategy must pass on its actual pin. If supported choices cannot pass, reopen architecture selection with the reproduced negative evidence.
