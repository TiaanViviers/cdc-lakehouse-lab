# EXP-002 — Source bridge gateway reachability

- Date and operator: 2026-11-25, Codex on local Ubuntu Linux.
- Branch and base: research/1.1-source-isolation from 664857f.
- Questions: R01 and R16 (setup prerequisite).
- Status: passed on the dedicated VM. Bare workstation blocked.

## Hypothesis and preconditions

A source-side client can resolve a peer while the host and off-bridge endpoints are unreachable. The negative experiment used disposable internal bridges and staged probe code on Engine 29.1.3.

## Procedure, observations and evidence

The [source runbook](../source-runbook.md) records the topology, commands, versions, expected payloads, routes, deadlines, individual observations and cleanup. The workstation client obtained the exact host marker and skipped startup. In the approved offline VM the two gateway listeners timed out only with their controls in place. The gate released the sentinel once. Removing a forwarding rule blocked it again even while all traffic probes passed.

## Interpretation and follow-up

A connected gateway requires explicit guest INPUT controls. VM rollback restored both host paths. Ticket 1.2 can use the tested procedure and must obtain a fresh pass on each actual source bridge. R01 and R16 still require their database and inspection evidence.

On review, the Compose handoff was tested with an external network referenced by full Engine ID. The sentinel's inspected endpoint matched that ID, even with an invalid default context and socket. Removing the network, then recreating its name and interface with a different ID, blocked both the gate and the Compose sentinel in each case. The [handoff record](../source-runbook.md#compose-handoff-experiment-2026-11-25) includes the commands, controls and cleanup. The existing offline unit suite now exercises the firewall, probe verdicts and startup gate.
