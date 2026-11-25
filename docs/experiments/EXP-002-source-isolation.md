# EXP-002 — Source bridge gateway reachability

- Date and operator: 2026-11-25, Codex on local Ubuntu Linux.
- Branch and base: research/1.1-source-isolation from 664857f.
- Questions: R01 and R16 (setup prerequisite).
- Status: blocked.

## Hypothesis and preconditions

A source-side client can resolve a peer while the host and off-bridge endpoints are unreachable. The negative experiment used disposable internal bridges and staged probe code on Engine 29.1.3.

## Procedure, observations and evidence

The [source runbook](../source-runbook.md) records the topology, commands, versions, expected payloads, routes, deadlines, individual observations and cleanup. The client obtained the exact host marker. The startup sentinel was skipped.

## Interpretation and follow-up

The connected host gateway defeats the proposed isolation on this machine. The packet-filter policy and successful dedicated-host procedure remain unverified. Keep issue #19 open and ticket 1.2 runtime blocked pending approval and reproduction on a dedicated VM.
