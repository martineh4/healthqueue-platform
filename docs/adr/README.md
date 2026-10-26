# Architecture Decision Records

We record significant, hard-to-reverse decisions as ADRs (Michael Nygard format).
ADRs are immutable once accepted; to change a decision, write a new ADR that supersedes it
and update the old one's status.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-azure-region-selection.md) | Azure region selection | Accepted |
| [0002](0002-opentofu-state-management.md) | OpenTofu state management | Accepted (amended by 0003) |
| [0003](0003-github-actions-workload-identity.md) | GitHub Actions workload identity and least-privilege CI roles | Accepted |
| [0004](0004-registry-pull-authentication.md) | Registry pull authentication for the cluster | Accepted |
| [0005](0005-sqlite-single-replica-data-store.md) | SQLite on a single replica; PostgreSQL for production | Accepted |
| [0006](0006-gitops-with-argo-cd.md) | GitOps delivery with Argo CD (app of apps) | Accepted |
| [0007](0007-pr-driven-image-promotion.md) | Pull-request-driven image promotion | Accepted |
| [0008](0008-observability-and-slos.md) | Observability stack and SLO-based alerting | Accepted |

To add one, copy [`template.md`](template.md) to `NNNN-short-title.md` using the next number,
and add a row above in the same pull request.
