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
