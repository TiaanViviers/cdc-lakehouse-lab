# GitHub ticket numbering and issue conventions

## Stable ticket ID

Every GitHub **issue title** begins with **`phase.sequence`**, followed by a space and an imperative, concise title:

- `0.1 Verify supported DuckPipe/PostgreSQL versions`
- `1.12 Implement Python generator`
- `4.3 Materialize Silver tables using Windmill`
- `5.2 Expose Gold Reporting through a SQL endpoint`
- `6.4 Implement idempotent production write-back`

**Do not confuse** these project IDs with GitHub's immutable repository-wide issue numbers (`#17`, `#18`) or pull request numbers. The project ID is stable even if tickets are reordered, split or moved on a GitHub Project board.

## Numbering rules

1. Phase IDs correspond exactly to [roadmap phases 0–8](roadmap.md).
2. Sequence begins at 1 **independently within each phase** and increases for newly created issues. No requirement to have consecutive issues open at any point.
3. No zero-padding: `1.1`, `1.2`, `1.12`. Treat IDs as strings, never decimal numbers or floating-point values.
4. Before publishing a ticket, inspect `backlog/tickets.yaml` and existing open/closed GitHub issues; allocate the next unused ID *for its phase*. Reserve/update the registry in the same planning change where possible.
5. Never reuse a closed/cancelled/superseded ID and never renumber a published issue. If work changes phase, keep the original ID and add a note or create a newly numbered issue linked to it.
6. One specific outcome per issue. For a large feature, publish an umbrella issue and smaller dependent issues, each with its own ticket ID.
7. GitHub **milestones** indicate phases. Use only the minimal label set in [project management](project-management.md); do not create `phase:*` labels or duplicate board Status in labels.
8. Refer to both identities when necessary, e.g. **`1.12 (#38)`**.
9. Split or duplicate issue collisions must be resolved in the registry before any new issue is published.
10. PR titles may reference ticket IDs (e.g. `1.12: add deterministic generator`); PRs do not consume a new issue ID.

## Required issue content

- Stable ticket ID and phase; title as above.
- Objective and relevant `Rxx` research-question references.
- Scope and explicit exclusions.
- Dependencies (use stable IDs, and links when issued).
- Implementation or experiment procedure.
- Verifiable acceptance criteria, commands and expected evidence.
- Security/cleanup and failure considerations.
- Documentation and experiment report updates.

Use the GitHub issue forms. Because GitHub cannot automatically assign this custom ID, **agents must allocate and verify it explicitly** before clicking Publish. GitHub's numeric `#` sequence continues independently.

## Backlog lifecycle

Phase tickets are planned and published **one phase at a time**, never generated for the entire roadmap. The initial repository contains no published phase tickets by default. Proposed issues should first be drafted and reviewed with dependencies and appropriate granularity. Once approved, create them through the GitHub plugin or CLI, using idempotent checks against ticket IDs.

The [ticket registry](../backlog/tickets.yaml) is a small machine-readable index; it is not a full issue body store. A later planning pass can populate it and publish GitHub issues. Changes to ticket status must not erase historical IDs.

## Mandatory phase handover ticket

The **last ticket to be completed in each milestone** is a handover issue to review the phase and **create the next phase's milestone and approved tickets**. Draft this transition ticket with the rest of the current-phase backlog. It remains open until current-phase findings/ADRs are reconciled, next-phase issues are reviewed and published, milestone assignments are correct, and the new work is on the board.

The transition ticket is **last by completion**, not guaranteed to have the highest numeric ID if research introduces new tickets later. Never renumber it. Phase 8 has a final project closeout issue rather than inventing Phase 9. See [the checklist and exact procedure](project-management.md#mandatory-final-transition-issue).
