# ADR-0006: GitOps delivery with Argo CD (app of apps)

- **Status:** Accepted
- **Date:** 2026-10-25
- **Deciders:** Platform engineering; informed: CTO
- **Related:** [ADR-0004](0004-registry-pull-authentication.md),
  [ADR-0005](0005-sqlite-single-replica-data-store.md), [`deploy/`](../../deploy/README.md),
  [supply chain and SLSA](../supply-chain-slsa.md)

## Context

The cluster must run exactly what is on `main`, and every change must go through a reviewed
pull request. That applies to the application and to the delivery tooling itself.

The cluster is kind inside a GitHub Codespace (assignment constraint: no Docker on the
engineer's laptop). GitHub-hosted runners cannot reach it: it has no public endpoint, and it
exists only while the Codespace runs.

Requirements:

1. **Pull, not push.** No CI system holds credentials to the cluster.
2. **Git is the only source of truth,** including for Argo CD's configuration and version.
3. **Drift is reverted** automatically, and visible.
4. **Blast radius limits.** An application's manifests cannot create objects outside its
   namespace or of unexpected kinds, even if a bad change is merged.
5. **Supply-chain parity.** The delivery tooling is pinned as strictly as the application:
   commit-pinned manifests and digest-pinned images.
6. **Recreatable in minutes,** because the Codespace cluster is disposable.

## Decision

### Argo CD, installed once, then self-managed

- `deploy/argocd/install` references the upstream `install.yaml` at the **commit** of the
  v3.5.4 tag and overrides all three images (Argo CD, Dex, Redis) with **digests**. Upgrading
  Argo CD is a pull request that changes the commit and the digests together.
- The `argocd` Application syncs that directory: Argo CD manages itself. Its sync policy has
  `selfHeal: true` but **`prune: false`**, so a bad commit cannot delete Argo CD's own
  components. Server-side apply is required because the CRDs exceed client-side apply's
  annotation limit.

### App of apps

`deploy/scripts/bootstrap-cluster.sh` applies the `root` Application by hand, once. The
three AppProjects go first: `root` belongs to the `platform` project, and Argo CD will not
start an Application whose project does not exist yet ("project platform which does not
exist", found during the first live bootstrap). `root` then adopts the projects from Git,
so a later change to them is still a pull request. `root` syncs `deploy/argocd/`, which holds:

| Object | Purpose |
|---|---|
| `AppProject default` | **Locked down** (no sources, destinations or kinds), so no Application can silently use Argo CD's permissive default project |
| `AppProject platform` | Argo CD itself and the root. Cluster-wide kinds are allowed (CRDs, ClusterRoles), but only from this repository and only into `argocd` |
| `AppProject healthqueue` | Destination `healthqueue` only. Cluster kinds: `Namespace` only. Namespaced kinds: exactly those in `deploy/overlays/prod` (Deployment, Service, ConfigMap, ServiceAccount, PVC, NetworkPolicy) |
| `Application argocd` | Self-management (above) |
| `Application healthqueue-api` | `deploy/overlays/prod`, automated sync with `prune` and `selfHeal`, retry with back-off |
| `Application root` | Itself, so the root is under Git control too |

The `healthqueue` project is the enforcement point for requirement 4. A merged manifest that
adds a `ClusterRoleBinding`, a `Secret`, or a Deployment in another namespace fails to sync
with a project violation instead of reaching the cluster.

### Safety defaults

- **No cascade deletion.** Neither application has the resources finalizer. Deleting an
  Application stops management but leaves the running service in place.
- **The database volume is protected:** `Prune=false,Delete=false` on the PVC. Losing data
  always takes a manual act.
- **`PruneLast=true`.** Removed objects are deleted only after the rest of the sync is
  healthy.

### The pull secret stays outside Git

The `acr-pull` Secret is created by `create-pull-secret.sh` (ADR-0004), not by Argo CD. Argo CD
does not track it, so it is never pruned and never appears in a diff. `--stdin` mode lets the
password be minted on a workstation with Azure access and piped into the Codespace over
`gh codespace ssh`. The Codespace then never needs an Azure login with registry rights.

## Consequences

**Positive**

- **Merge = deploy.** Phase 8's digest-bump PR is the entire release step, and reverting the
  merge commit is the rollback.
- Every change to the cluster, including Argo CD upgrades and project permissions, has a pull
  request, a review trail and CI checks (`manifests` validates the Applications and AppProjects
  against their CRD schemas and checks every image is digest-pinned).
- Manual `kubectl edit` changes are reverted within one reconciliation, and Argo CD shows
  them as drift.

**Negative / accepted risks**

- **The `platform` project is broad.** Anyone who can merge to `main` can change what Argo CD
  installs cluster-wide. This is the same trust boundary as branch protection; a second
  maintainer and required reviews (SLSA gaps table) are the mitigation.
- **Argo CD's upstream manifests are not policy-scanned by Trivy.** Their controllers need
  cluster-wide RBAC by design and would fail any "least privilege" rule. They are validated
  against schemas, digest-checked, and pinned to an upstream commit.
- **Polling, not webhooks.** The Codespace has no inbound endpoint for GitHub webhooks, so
  syncs happen within Argo CD's default 3-minute polling interval. This adds up to 3 minutes of
  lead time to DORA measurements.
- **Admin password login.** The kind installation uses Argo CD's generated `admin` password
  (UI only via port-forward). Production would disable `admin` and use SSO (Entra ID through
  Dex or OIDC) with RBAC groups.
- **Single cluster, single environment.** Staging would be another overlay and Application. An
  ApplicationSet would generate them once there are several.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Push-based deploys from GitHub Actions (`kubectl apply`) | The runner cannot reach the cluster. Even if it could, CI would need cluster-admin credentials, failing requirement 1. |
| Flux | Equally valid GitOps engine. Argo CD's UI makes sync state, drift and history visible to a non-specialist audience (CTO, assessors), and AppProjects give a clear permission boundary. |
| Argo CD Image Updater (auto-bump on new image) | Changes the deployed version without a pull request, bypassing review and the PR-driven requirement. Phase 8 uses a bot-opened PR instead. |
| Helm chart for Argo CD | Adds a templating layer and values file to audit. The plain upstream manifest at a pinned commit, plus kustomize image overrides, is simpler to verify. |
| Vendoring `install.yaml` into the repository | Makes upgrade diffs about 30k lines. A commit-pinned remote reference is equally immutable. |

## Revisit when

- A second environment exists: ApplicationSet over overlays.
- The cluster moves to AKS: enable webhooks, SSO, and Argo CD notifications to the team channel.
- Phase 9: add Kyverno through the `platform` project, so admission policy is also GitOps-managed.
