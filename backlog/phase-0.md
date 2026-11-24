# Proposed Phase 0 tickets — review before publication

> **Status: draft proposal only.** These are *not* GitHub issues. Only Phase 0 tickets are proposed; future phases will be planned from experiment results. See [roadmap](../docs/roadmap.md), [project workflow](../docs/project-management.md), [numbering](../docs/issue-conventions.md) and [registry](tickets.yaml).

**Milestone:** [Phase 0 — Foundation](https://github.com/TiaanViviers/cdc-lakehouse-lab/milestone/1)  
**Project board:** [CDC Lakehouse Lab](https://github.com/users/TiaanViviers/projects/3)  
**Goal:** Finish with an evidence-grounded compatibility baseline, realistic synthetic source design, reproducible local development conventions, and a reviewed Phase 1 backlog. **No database runtime implementation is required within this planning phase.**

### Proposed dependency order

```text
0.1 Version research ─────► 0.2 Docker topology ─► 0.5 Tooling ─┐
0.3 Synthetic fixtures ───► 0.4 Evidence protocol ───────────────┼─► 0.6 Phase 1 handover
                                                                  │
                               0.1, 0.2, 0.3 also feed handover ──┘
```

The initial **Ready** candidates are `0.1` and `0.3`. Other tickets should remain in **Backlog** until prerequisites are satisfied. Normal priority is unlabelled.

---

## 0.1 Verify component compatibility and candidate versions

**Type:** `research`; **priority:** `priority:high`; **dependencies:** none.  
**Research links:** R01, R06–R07, R09–R11, R17, R22.

**Objective:** Establish what we can *actually* run and connect, before creating implementation Docker files.

**Scope**
- Consult up-to-date official documentation and release/image references for: PostgreSQL 16 source; remote `pg_duckpipe` and `pg_ducklake` requirements; DuckLake catalog and DuckDB; S3-compatible local storage; self-hosted Windmill server/workers/Flows/Pipelines; separate `pg_ducklake` SQL serving; request API/DB prerequisites.
- Record exact candidate versions, supported host/extension versions, image tags or digests and their provenance.
- Distinguish documented support, assumed compatibility and integration gaps. Highlight GitHub repository/documentation ambiguities instead of filling them in by guesswork.
- Document licensing/edition and architectural caveats relevant to a public reproducible lab.
- Research only: do **not** claim a runtime stack works, provision cloud resources or replace tools silently.

**Acceptance criteria**
- [ ] `docs/compatibility-matrix.md` compares all listed components, specific candidate versions, supported PostgreSQL versions, required extensions, known issues and official source URLs with access dates.
- [ ] One-page risk/decision summary identifies the **first integration uncertainty to test**, alternatives and impact on later phases.
- [ ] S3 emulation and Windmill Pipeline maturity are recorded as evidence-backed choices or unresolved questions.
- [ ] A reviewer can distinguish **documented** support from **not yet runtime-tested** compatibility.
- [ ] Any choice changing intended topology is proposed through an ADR, not silently introduced.

**Evidence:** Links, release references and explicit unknowns; no green tests asserted without execution.

---

## 0.2 Design local Docker topology and isolation boundaries

**Type:** `docs`; **dependencies:** 0.1.  
**Research links:** R07, R15.

**Objective:** Translate the existing [logical diagram](../docs/Data_System.drawio) into a safe, incremental Docker model without creating five actual EC2 machines.

**Scope**
- Define logical services/network boundaries: source PostgreSQL; separate DuckPipe/catalog PostgreSQL; Windmill internal PostgreSQL + server and workers; separate reporting query service; request API/DB and write-back; one local S3-compatible server with **two distinct buckets**; independent DuckDB client; optional inspection tools.
- Identify persistent volumes, safe port exposure, inter-service credentials, synthetic data isolation, health checks and startup dependencies.
- Define laptop-sized resource defaults for ~16 GB RAM and phase-based Compose bring-up.
- Specify which processes can co-locate in development, and what must stay independent **logically**.
- Do not implement full Compose/service images in Phase 0.

**Acceptance criteria**
- [ ] `docs/local-runtime-design.md` contains a service table (name, role, dependencies, storage, ports, health signal).
- [ ] Network/security model prevents accidental production access and distinguishes separate catalog, Windmill, request and query databases.
- [ ] S3 DuckLake data and operational batch storage have explicitly separate bucket/credential conventions.
- [ ] Baseline resource/port budget and incremental startup plan are documented.
- [ ] List of unanswered runtime-specific configuration questions for first implementation tickets is recorded.

**Evidence:** Human-readable design diagram/table and reviewed boundaries.

---

## 0.3 Specify synthetic source schema and deterministic fixtures

**Type:** `docs`; **dependencies:** none.  
**Research links:** R02, R03, R13.

**Objective:** Define a useful generic operational workload and precise expected outcomes before writing the generator.

**Scope**
- Design a small generic source domain: customers, orders, order items, payments (or evidence-backed equivalent).
- Specify PK/FK relationships, unique constraints, transaction boundaries, update/delete behaviour, key ordering and source timestamps.
- Define fixed-seed scenarios: bootstrap, insert, update, delete, atomic multi-table transaction, concurrent transaction and replay.
- Include a small voucher-like **synthetic token** concept only if needed as future Phase 6 design context; no real coupon/customer/business details.
- State how row-level parity and expected reporting aggregates will be checked, not only counts.

**Acceptance criteria**
- [ ] `docs/synthetic-workload.md` describes schema, example records, deterministic seed/scenario IDs, transaction patterns and edge cases.
- [ ] Expected source states and at least one Gold Reporting aggregate are specified with manually checkable examples.
- [ ] Timestamp/timezone handling, delete expectations and idempotent generator reset are documented.
- [ ] Test datasets are purely fictional, small and licence/privacy-safe.
- [ ] Open questions to be decided during Phase 1 are separated from fixed requirements.

**Evidence:** Schema description, sample cases, expected row keys and aggregate calculations.

---

## 0.4 Define phase-level correctness and observability protocol

**Type:** `research`; **dependencies:** 0.3.  
**Research links:** R04–R05, R13, R16, R21, R25.

**Objective:** Make it impossible for coding agents to call a phase successful based only on healthy containers or successful scripts.

**Scope**
- Define generic evidence to collect at each data boundary: source record/transaction; slot/LSN; DuckPipe status; DuckLake catalog/snapshots; S3 objects; independent DuckDB values; Windmill job IDs; query-service results; async request/S3 artifact/write-back receipts.
- Define row-level parity, deletion, stable snapshot, timing and failure experiment templates.
- Explain acceptable limitations of WAL acknowledgements, eventual consistency, and cross-table cutoffs.
- Design a minimal, browser-visible investigation workflow using existing tools *before* custom dashboards.
- No full dashboard implementation yet.

**Acceptance criteria**
- [ ] `docs/verification-plan.md` contains a phase-gate checklist and a simple traceability matrix mapping research IDs to evidence and experiments.
- [ ] At least one end-to-end synthetic transaction walkthrough explains where to inspect each state and what it does **not** prove.
- [ ] Failure-injection safety rules and recovery evidence requirements are explicit.
- [ ] Record run ID / scenario ID conventions and where test output or redacted evidence should be stored.
- [ ] Clearly separate metadata progress, job success, data correctness and operational commitment.

**Evidence:** Reviewable verification protocol with reproducible planned checks; do not fabricate outputs.

---

## 0.5 Establish minimal repository developer tooling

**Type:** `feature`; **dependencies:** 0.2.  
**Research links:** none directly.

**Objective:** Make the repository convenient and safe for future coding agents without building a framework prematurely.

**Scope**
- Add only simple, portable local developer commands or a `Makefile` with help and relevant documentation/format validation.
- Add a minimal CI check that meaningfully runs on the current documentation-only repository. Avoid pretending tests exist before code is added.
- Provide a safe `.env.example` with **placeholder values only** and update `.gitignore` if necessary for local secrets, volumes and experiment outputs.
- Document branch/PR workflow, prerequisites and where future unit/integration tests attach.
- Avoid Docker configuration/actual database source implementation within this ticket.

**Acceptance criteria**
- [ ] `make help` or an equally simple documented command lists current developer actions and runs locally.
- [ ] CI validates at least one real repository property (e.g., manifest structure or Markdown references) and passes on this branch.
- [ ] Secret/data exclusions are reviewed; no actual credentials or generated object files are committed.
- [ ] README/development instructions state exactly which checks were executed and which are planned for later phases.
- [ ] No spurious dependencies, complex workflow engine or duplicate GitHub automation introduced.

**Evidence:** CI run URL and exact local verification commands, or recorded blocker if CI was unavailable.

---

## 0.6 Review Phase 0 findings and publish Phase 1 tickets

**Type:** `docs`; **dependencies:** 0.1–0.5.  
**Special:** **Mandatory phase transition — last ticket to be completed in milestone**.

**Objective:** Reassess the design using Phase 0 findings and create **only Phase 1** milestone and approved issues.

**Scope / acceptance criteria**
- [ ] Verify Phase 0 gate: compatibility/version matrix, runtime plan, synthetic schema, verification protocol and developer tooling have been reviewed and documented. Record any incomplete acceptance criteria.
- [ ] Update architecture, research question statuses, ADRs and roadmap based on documented findings; do not report hypotheses as tested.
- [ ] Draft small independently testable Phase 1 issues for the PostgreSQL simulator only, each with a stable `1.N` ID, dependencies, acceptance criteria and evidence requirements.
- [ ] Review/approve those Phase 1 issue drafts; update `backlog/tickets.yaml` without reusing IDs.
- [ ] Create `Phase 1 — Operational Source Simulator` GitHub milestone **only after approval**.
- [ ] Publish approved Phase 1 issues, assign that milestone, and add them to the **same Project board**, using Ready/Backlog as appropriate.
- [ ] Close the Phase 0 milestone and only then mark this handover issue Done (or document GitHub's practical closing sequence if required).

**Evidence:** Phase 0 closeout summary, revised docs/ADRs, links to Phase 1 milestone, issue list and board.

**Important:** This ticket is last **by completion**, not necessarily by numerical ID if additional `0.N` issues are discovered later.

---

## Review and publication procedure

1. Review this proposal and `backlog/tickets.yaml` through a GitHub pull request.
2. Refine/split/reorder issues if their requirements are too broad.
3. Once approved, publish only these Phase 0 issues, assign the existing Phase 0 milestone and appropriate labels, and add them to [the board](https://github.com/users/TiaanViviers/projects/3).
4. Mark 0.1 and 0.3 Ready; remaining tickets Backlog until dependencies are met.
5. The final Phase 0 issue 0.6 is the **only** mechanism that publishes Phase 1 tickets once Phase 0 findings are known.
