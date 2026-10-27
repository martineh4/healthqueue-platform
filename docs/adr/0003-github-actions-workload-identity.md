# ADR-0003: GitHub Actions workload identity and least-privilege CI roles

- **Status:** Accepted
- **Date:** 2026-10-25
- **Deciders:** Platform engineering; informed: CTO, security
- **Related:** [ADR-0002](0002-opentofu-state-management.md), [`infra/README.md`](../../infra/README.md),
  [`.github/workflows/infra.yml`](../../.github/workflows/infra.yml)

## Context

From phase 4 onwards, infrastructure changes reach Azure only through GitHub Actions: plan on
pull request, apply on merge. Phase 5 adds a release workflow that pushes images and uploads
release evidence. Each of these pipelines needs Azure credentials.

The usual approach is a service principal with a client secret stored as a GitHub secret. That
secret can be read by anything that runs in a workflow with access to it. It is valid until
someone remembers to rotate it, and it usually holds `Contributor` on the whole subscription.
A single compromised action, as happened with the Trivy GitHub Action in March 2026, can
exfiltrate it.

Requirements:

1. **No long-lived cloud credentials** stored in GitHub or anywhere else.
2. **Pull requests cannot change infrastructure.** A PR plan must be read-only, even if the PR
   edits the workflow file.
3. **Only reviewed code on `main` can apply.**
4. **CI cannot widen its own permissions.** It must not be able to grant itself, or a new
   identity, roles it does not already need.
5. **Blast radius of one environment.** A compromised pipeline for one environment cannot touch
   state, keys or resources of another environment.

## Decision

### OpenID Connect federation to user-assigned managed identities

GitHub issues each job a short-lived OIDC token. Azure exchanges it for an access token only if
the token's `sub` claim exactly matches a **federated credential** on a user-assigned managed
identity. No secret exists to steal. The client, tenant and subscription IDs are stored as GitHub
secrets only so the public workflow logs show them masked. The IDs grant nothing on their own.

The repository uses GitHub's **immutable subject format**, which embeds the owner and repository
numeric IDs:

```
repo:martineh4@230047607/healthqueue-platform@1432743551:<context>
```

If the repository were deleted and someone re-created one with the same name ("repojacking"),
its tokens would carry a different repository ID and match no credential.

### One identity per job role, per environment

| Identity | Created by | Federated subject (`<context>`) | Roles |
|---|---|---|---|
| `id-hq-tofu-prod-plan` | bootstrap | `pull_request`, `ref:refs/heads/main` (drift check) | `Reader` on `rg-healthqueue-prod`; `Storage Blob Data Reader` on container `tfstate-prod`; `Key Vault Crypto User` on key `tfstate-prod` |
| `id-hq-tofu-prod-apply` | bootstrap | `environment:prod` | `Contributor` on `rg-healthqueue-prod`; constrained `Role Based Access Control Administrator` on the same group (see below); `Storage Blob Data Contributor` on `tfstate-prod`; `Key Vault Crypto User` on `tfstate-prod` |
| `id-hq-release` | envs/prod | `environment:release` | `AcrPush` on the registry; `Storage Blob Data Contributor` on container `release-evidence` |

How this meets the requirements:

- **Requirement 2.** The plan identity has no write role anywhere. A PR that rewrites
  `infra.yml` to run `tofu apply` still authenticates as the plan identity and fails. Fork PRs
  receive no OIDC token at all. Because a lease is a write, PR plans run with `-lock=false`.
  They are advisory: the apply job re-plans under a lock.
- **Requirement 3.** The apply identity trusts only tokens for the `prod` GitHub environment.
  That environment accepts deployments only from protected branches (`main`), and `main` accepts
  changes only through a PR with passing checks.
- **Requirement 4.**
  - The identities and their federated credentials live in `rg-healthqueue-tfstate`, where the
    apply identity has no role. It cannot add a credential trusting, say, every branch.
  - Its role-assignment right is an **ABAC-conditioned** `Role Based Access Control
    Administrator`. It may create or delete assignments only for `AcrPull`, `AcrPush` and
    `Storage Blob Data Contributor`, only for service principals, and only inside
    `rg-healthqueue-prod`. It cannot grant `Owner`, `Contributor` or anything to a user.
- **Requirement 5.** Each environment has its own state **container**, not just its own blob,
  so the roles above can be scoped at container level. The bootstrap state and other
  environments' state are unreachable.

### The bootstrap owns the environment's resource group

A resource group's role assignments must exist before CI can manage anything in it. The
bootstrap therefore creates `rg-healthqueue-<env>` and its CI identities. The environment
configuration reads the group with a data source and manages only what is inside it. The
phase 3 resource group was moved with an `import` block in the bootstrap and a `removed`
block in `envs/prod`, so nothing was recreated.

### Registry and release evidence (envs/prod)

- **Azure Container Registry, Basic SKU, admin user disabled.** Private endpoints, retention
  and content-trust features need Premium (about $50/month), which is out of proportion for a
  student subscription. Integrity comes from cosign signatures and digest pinning (phase 5)
  instead.
- **Release evidence storage** holds SBOMs, scan reports and provenance in the
  `release-evidence` container. It has the same Entra-only hardening as the state account and a
  **container-level WORM immutability policy**: once written, evidence cannot be changed or
  deleted for the retention period, not even by the identity that wrote it. The policy is
  **unlocked with 7-day retention** so the course environment can be torn down. Production would
  lock it at 2190 days (six years, the HIPAA documentation retention period). A locked policy is
  irreversible and blocks deleting the account.

## Consequences

**Positive**

- Zero stored credentials. Revoking CI access means deleting a federated credential or a role
  assignment, and that takes effect immediately.
- Every Azure action by CI is attributable to a named identity in the activity log, which says
  whether it came from a PR plan, an apply or a release.
- Each workflow is limited to the minimum it needs. A compromised release job could push an
  image, which still has to pass signature verification at deploy time. It could not alter
  infrastructure or state.

**Negative / accepted risks**

- **The apply identity is powerful inside `rg-healthqueue-prod`.** It can delete anything there.
  Mitigations: only reviewed code on `main` runs as it, every apply is preceded by a plan visible
  in the PR, and the state is versioned. A required reviewer on the `prod` environment would add
  a human gate. It is not configured because the repository has a single maintainer, and
  self-approval adds nothing.
- **The apply identity can create a new managed identity, give it a federated credential with
  any subject, and grant it `AcrPush`.** That is the price of letting the environment manage its
  own workload identities. The condition caps the possible damage at pushing images, which still
  need a valid signature to deploy (phase 9).
  *Amended 2026-10-26:* phase 9 is deferred, so the cluster does not check signatures yet. Until
  it does, the control is that production runs only a digest merged through a reviewed deploy
  pull request (ADR-0007).
- **PR plans skip locking.** A PR plan can read state mid-apply and show a stale diff. It cannot
  cause damage because it can write nothing.
- **Dependabot PRs get no plan.** GitHub does not expose Actions secrets to Dependabot. Provider
  bumps are planned and applied, under lock, on merge.
- **Public network endpoints** on the state and evidence accounts and the registry. See the
  ADR-0002 risk acceptance, which expires 2027-04-30.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Service principal + client secret in GitHub | Long-lived, exfiltratable secret; fails requirement 1. |
| App registration with federated credentials | Equivalent security, but needs Entra ID application-administrator rights that a student tenant may not grant, and lives outside the subscription's resource lifecycle. Managed identities are plain Azure resources managed by OpenTofu. |
| One identity for plan and apply | A PR could then modify infrastructure; fails requirement 2. |
| `User Access Administrator` for the apply identity | It could grant itself `Owner`; fails requirement 4. |
| Subject `ref:refs/heads/main` for apply | Any workflow on `main` (including a scheduled drift check) could then apply. Environments also add deployment history and an optional approval gate. |
| ACR Premium with private endpoint | About 10× the cost; GitHub-hosted runners would need a self-hosted runner in the VNet to push. |
| GitHub Container Registry only | Free and simpler, but the assignment is Azure-centred, and ACR keeps image access under the same Entra RBAC and audit trail as everything else. |

## Revisit when

- A second maintainer joins: add a required reviewer on the `prod` environment.
- Self-hosted runners or a private network exist: remove public endpoints and close the
  ADR-0002 risk acceptance.
- Real PHI is processed: lock the evidence immutability policy at 2190 days.
