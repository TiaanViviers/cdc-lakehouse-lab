# Ticket registry

`tickets.yaml` reserves project ticket IDs in `phase.sequence` form and will map them to GitHub issue numbers when published.

The approved [numbering policy](../docs/issue-conventions.md) is `1.12 Implement Python generator` for phase 1, ticket 12. GitHub issue number `#NN` is separate and allocated by GitHub.

- [Phase 0 — Foundation](phase-0.md) is published. The [closeout and approval gate](../docs/phase-0-closeout.md) records the handover status.
- [Phase 1 — Operational Source Simulator](phase-1.md) is proposed. Registry entries with `status: proposed` reserve IDs without a GitHub issue number.

Populate the registry in a reviewed backlog-planning PR before issue creation. After publication update `github_issue` and `status`. Never recycle used IDs.

Ticket planning is **per phase**, not upfront for the whole roadmap. See [GitHub project workflow](../docs/project-management.md). Every phase includes a **final handover issue** to approve/create the *next* phase milestone and its tickets before closing the current one. Do not pre-register unreviewed future-phase tickets.
