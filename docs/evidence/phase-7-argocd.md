# Evidence: Phase 7, GitOps delivery with Argo CD on kind

Captured 2026-10-26 in a GitHub Codespace (`standardLinux32gb`, 4 cores and 16 GB). Design:
[ADR-0006](../adr/0006-gitops-with-argo-cd.md), [ADR-0004](../adr/0004-registry-pull-authentication.md),
[`deploy/`](../../deploy/README.md).

## 1. Codespace tooling (PR #13)

The first Codespace on `main` failed to build its dev container (error 1302) and fell back to a
recovery container with no Docker and none of the tools. Root cause: the
`devcontainers/python` base image ships a Yarn apt source without its signing key
(`NO_PUBKEY 62D54FD4003F6525`), so `apt-get update` failed inside the docker-in-docker
feature's installer.

PR #13 fixed it:

- **`.devcontainer/Dockerfile`:** the same base image, pinned by digest, with the Yarn source
  removed. The build fails if the source is still referenced.
- **`sshd` feature added:** the bootstrap is driven over `gh codespace ssh`.

The rebuilt Codespace verified all seven pinned CLIs against the SHA-256 sums in
`post-create.sh`:

```
kind     v0.33.0  verified      cosign   v3.1.3   verified
kubectl  v1.37.1  verified      tofu     1.13.1   verified
argocd   v3.5.4   verified      trivy    0.75.0   verified
syft     v1.54.1  verified      docker 29.9.2 (docker-in-docker)
```

## 2. Bootstrap

| Run | Result |
|---|---|
| Pass 1, fresh cluster | kind node `v1.37.0` (containerd 2.3.4) Ready after 15 s. Argo CD rolled out. **Stopped at step 3 with exit 2**, because `acr-pull` did not exist yet (by design) |
| Pull secret | Minted on the workstation and piped in with `--stdin` (below) |
| Pass 2 | **Stalled:** `root` reported "Application referencing project platform which does not exist" |

**Bug found:** `root` belongs to the `platform` AppProject, but that project is defined inside
the directory `root` syncs. Applying the three AppProjects by hand confirmed the diagnosis:
within about 40 s, `root`, `argocd` and `healthqueue-api` were all Synced and Healthy.

**Fix (PR #14):** step 4 now server-side-applies `deploy/argocd/projects/` before `root`, and
`root` adopts them from Git. ADR-0006 is amended. The fix was then proven from scratch:

| Run | Result |
|---|---|
| `kind delete cluster`, pass 1 | Stopped at step 3, exit 2 (as designed) |
| Fresh pull secret | Minted and piped in (also a rotation; see section 4) |
| Pass 2 | **Exit 0 in 24 s:** projects seeded, `root` applied, `healthqueue-api` Synced and Healthy |
| Pass 3, re-run unchanged | Exit 0. Cluster `exists`, projects `serverside-applied`, no warnings: **idempotent** |

```
NAME              SYNC STATUS   HEALTH STATUS
argocd            Synced        Healthy
healthqueue-api   Synced        Healthy
root              Synced        Healthy
```

## 3. Workload verification

| Check | Result |
|---|---|
| Image running | `crhealthqueueora3w.azurecr.io/healthqueue-api@sha256:46994651…dfe59f5`, pulled with the pull-only token |
| Signature of the running digest | `cosign verify`, identity `release.yml@refs/heads/main`, issuer GitHub Actions OIDC: **passed** (claims, transparency log, certificate chain) |
| Process identity | `uid=10001(app) gid=10001(app)`, 0 restarts |
| Namespace labels | `pod-security.kubernetes.io/enforce=restricted`, `enforce-version=v1.37`, plus `audit` and `warn` |
| PSA enforcement | `kubectl run --privileged` **rejected**: `violates PodSecurity "restricted:v1.37"` (privileged, allowPrivilegeEscalation, capabilities, runAsNonRoot, seccompProfile) |
| Probes | `/healthz` 200, `/readyz` 200; the pod is `Ready=True`; liveness and readiness use those paths |
| PVC | `healthqueue-data` 1Gi RWO, Bound (`standard` local-path class) |
| NetworkPolicy from namespace `np-test` | **000, timed out**: default-deny-all enforced by kindnet |
| NetworkPolicy from namespace `monitoring` | **200**: the one allowed ingress source (for Prometheus, phase 10) |

## 4. GitOps controls

| Check | Result |
|---|---|
| Self-heal | `kubectl scale --replicas=0` reverted to `replicas=1` within about 2 s, then rolled out again |
| AppProject boundary | An Application in project `healthqueue` targeting `kube-system` was refused: `InvalidSpecError: … do not match any of the allowed destinations in project 'healthqueue'`. Nothing was synced; the test Application was deleted |
| Pull secret outside Git | `acr-pull` created by `create-pull-secret.sh --stdin`; labelled `managed-by=create-pull-secret.sh`; not tracked by Argo CD |

The pull-secret password was minted on the workstation and piped over the SSH channel, never
printed or saved to disk:

```
az acr token credential generate -r crhealthqueueora3w -n kind-pull --password1 \
    --expiration-in-days 30 --query "passwords[?name=='password1'] | [0].[value, expiry]" -o tsv \
  | gh codespace ssh -c <codespace> -- 'cd /workspaces/healthqueue-platform && deploy/scripts/create-pull-secret.sh --stdin'

healthqueue/acr-pull: token kind-pull, expires 2026-11-25T03:29:51.566120+00:00 (29 days left)
```

Minting `password1` again replaced the earlier password. Afterwards, ACR shows the token
`enabled` with exactly **one** password, expiring 2026-11-25. The Codespace never had an
Azure login.

## 5. Not yet demonstrated

- **Digest bump through a PR:** promotion of a new release to the cluster is phase 8.
- **Signature enforcement at admission:** Kyverno, phase 9. Today the signature is verified
  in the pipeline and was checked by hand above, but the cluster does not enforce it.
- **Expiry alert for the pull secret:** phase 10. Today it is checked by `create-pull-secret.sh status`.
