# GitHub project workflow

A deliberately lightweight workflow for **one maintainer plus coding agents**. This is a process specification. It does not imply that the Project board, milestone or labels have already been created on GitHub.

## One project board

Create **one GitHub Project** called `CDC Lakehouse Lab` (a **Board** view) and add this repository's issues. Use exactly four Status options:

| Status | Meaning |
| --- | --- |
| **Backlog** | Proposed or approved work that cannot start yet, including work blocked on another ticket |
| **Ready** | Scoped, reviewed, and unblocked; safe for a coding agent to pick up |
| **In Progress** | Someone or an agent is actively working on it; link the PR or experiment |
| **Done** | Acceptance criteria verified, evidence/notes recorded, required PR merged or experiment concluded |

Use the board for visibility, not as an additional specification database. **GitHub Issues are the source of truth** for task descriptions, dependencies and outcomes. Move statuses manually at first; don't build automation or custom fields unless a real need emerges.

## Milestones — one active phase at a time

- Create **`Phase 0 — Foundation`** to start. Its scope is defined in [the roadmap](roadmap.md).
- The current phase's issues belong to its GitHub **milestone**. Avoid separate `phase:X` labels; milestones already provide phase grouping.
- **Do not create milestones for future phases in advance.** The milestone for phase N+1 is created during the final transition ticket for phase N, after learning from that phase.
- No artificial dates or sprints. Progress is determined by objective acceptance gates, not calendar time.
- A GitHub Project board is shared across all phases; completed issues remain on it with Status **Done**.

## Minimal labels

Create only these labels; add none when they do not help triage.

| Label | Usage |
| --- | --- |
| `feature` | Implementation of a capability |
| `research` | Hypothesis-driven experiment or compatibility investigation |
| `bug` | Reproducible defect or regression |
| `docs` | Documentation-only task |
| `priority:high` | Unblocks the critical path or urgent correctness issue |
| `priority:low` | Useful but not on the critical path |
| `blocked` | Cannot progress until a specified dependency is resolved |

Normal priority is **unlabelled**. Use at most one primary work-type label where practical. A blocker must be explained in the issue, not merely labelled. No per-area, per-status or per-phase labels initially.

## Stable ticket names

Every issue title starts with `<phase>.<sequence>` followed by a concise imperative title, such as `1.12 Implement Python generator`. Sequence values are **strings**, independently allocated per phase; the GitHub issue number (e.g. `#28`) is separate. See [issue conventions](issue-conventions.md) and [ticket registry](../backlog/tickets.yaml).

## Plan only one phase ahead

1. **Before beginning Phase N:** Review current docs, findings, ADRs and the roadmap. Draft just Phase N tickets with hypotheses, scope, dependencies, acceptance criteria and verification evidence. Reserve IDs in `backlog/tickets.yaml`.
2. Review the draft backlog, then create the **current phase milestone** (for Phase 0, manually during initial setup), publish its approved tickets, associate them with that milestone and add them to the Project board.
3. Place unblocked reviewed issues in **Ready**, future/blocked work in **Backlog**; move work to **In Progress** when started, and **Done** only after evidence and review.
4. Discoveries during the phase may require new/revised issues and ADRs. Do not pre-create a fixed backlog for phases N+1, N+2, etc.
5. The **final issue to be completed in every milestone** is the **phase transition/handover ticket** described below.

## Mandatory final transition issue

**Every phase milestone must contain one `Plan Phase N+1 and publish its tickets` issue**, drafted along with that phase's other tickets. For example, a Phase 0 issue could be titled `0.7 Review Phase 0 and prepare Phase 1 backlog` (illustrative ID, not reserved).

Treat it as the **last issue to CLOSE/complete**, not necessarily the largest numeric ID: research may require adding new phase issues with higher sequence numbers. Do not renumber a published handover ticket to keep it numerically last.

### Transition issue acceptance criteria

- [ ] Confirm the current milestone's technical acceptance gate, tests, experiment reports and open blockers. Document unresolved risks.
- [ ] Update architecture, research question statuses, ADRs and roadmap to reflect **what was actually learned**.
- [ ] Re-scope the **next phase only** using that evidence; produce small agent-ready issues with stable `(N+1).sequence` identifiers and measurable acceptance criteria.
- [ ] Review and approve the next phase backlog; check ID collisions and update `backlog/tickets.yaml`.
- [ ] Create **`Phase N+1 — <name>`** GitHub milestone, publish the approved next-phase tickets, assign milestones, and put them on the same Project board (Ready/Backlog).
- [ ] Close the current milestone and then mark this transition issue Done. It is the **last phase work item** to be completed.

**Phase 8 exception:** There is no Phase 9 in the current plan. The final Phase 8 ticket is `Review findings and close out the research project` (or a reviewed successor-phase proposal if the roadmap evolves); it closes with a final feasibility report rather than inventing Phase 9 tickets.

### Planning exception

For Phase 0, create its own milestone as part of the initial GitHub setup **before** publishing Phase 0 tickets. We intentionally do not publish those tickets until they have been planned together.

## Quick setup via GitHub website

These are **one-time manual steps** if the integration cannot create Projects/milestones/labels:

1. On your GitHub profile, open **Projects → New project → Board**. Name it `CDC Lakehouse Lab`; configure Status: Backlog, Ready, In Progress, Done. Add issues from `TiaanViviers/cdc-lakehouse-lab` as they are created.
2. In the repository, open **Issues → Milestones → New milestone**. Create `Phase 0 — Foundation` without a due date.
3. Open **Issues → Labels → New label** and create the seven labels listed above (reuse existing exact matches).
4. When Phase 0 tickets are approved, create them with the `0.N` title prefix, assign the Phase 0 milestone, and add them to the board.

No Project automation, sprints, custom fields, complex label hierarchy or deadlines are necessary.

## Review/close rules

- A PR may be merged only after tests/validation and documented evidence; an experimental ticket can close with a negative or blocked conclusion if its research protocol was fulfilled.
- Do not mark the transition issue Done merely because all other issues are closed; the next milestone and **reviewed tickets must already exist**.
- Keep the milestone handoff issue open if there are unresolved decisions that prevent responsible next-phase planning.
