# Ticket registry

`tickets.yaml` reserves project ticket IDs in `phase.sequence` form and will map them to GitHub issue numbers when published.

The approved [numbering policy](../docs/issue-conventions.md) is `1.12 Implement Python generator` for phase 1, ticket 12. GitHub issue number `#NN` is separate and allocated by GitHub.

No implementation tickets are approved or published through this docs-only change. Populate the registry in a reviewed backlog-planning PR before issue creation, then update `github_issue` and `status` fields. Never recycle used IDs.
