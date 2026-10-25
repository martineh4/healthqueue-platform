# ADR-0004: Registry pull authentication for the cluster

- **Status:** Accepted
- **Date:** 2026-10-25
- **Deciders:** Platform engineering; informed: CTO, security
- **Related:** [ADR-0003](0003-github-actions-workload-identity.md),
  [`deploy/scripts/create-pull-secret.sh`](../../deploy/scripts/create-pull-secret.sh),
  [runbook: image pull failures](../runbooks/image-pull-failures.md)

## Context

The cluster pulls `healthqueue-api` images from a **private** Azure Container Registry
(`crhealthqueueora3w`, Basic SKU, admin user disabled). Anonymous pull is off, so the kubelet
needs a credential.

The cluster for this project is **kind running in a GitHub Codespace**, not in Azure. That rules
out the Azure-native answer: there is no Azure VM or VM scale set, so no managed identity for
the kubelet to authenticate with. Something has to hand the cluster a registry credential.

Requirements:

1. **Pull only.** The credential can read the one repository the cluster runs, and its
   signatures (needed for admission-time verification, phase 9). It cannot push, delete, or read
   other repositories.
2. **Expires.** A leaked credential stops working by itself, without anyone remembering to
   revoke it.
3. **Never in Git, and never in OpenTofu state.** State can be decrypted by the PR plan identity
   (ADR-0003), so a secret in state is readable by anything that can open a PR.
4. **Revocable at once**, through a reviewed change, with a break-glass path.
5. **Disposable.** The kind cluster is recreated often; producing a new credential must be one
   command.

## Decision

### A repository-scoped ACR token, with no password in IaC

`infra/envs/prod` defines, through the normal PR-plan-apply flow:

- **Scope map `healthqueue-api-pull`:** `repositories/healthqueue-api/content/read` and
  `repositories/healthqueue-api/metadata/read`, nothing else. `metadata/read` lets clients list
  referrers, which signature verification needs.
- **Token `kind-pull`**, bound to that scope map, `enabled = true`.

It deliberately does **not** use `azurerm_container_registry_token_password`. That resource
would generate the password inside OpenTofu and store it in state (requirement 3).

### Passwords are minted on demand, with an expiry, straight into the cluster

`deploy/scripts/create-pull-secret.sh`, run by an engineer whose Azure CLI login can generate
token credentials:

1. Asks ACR for a new `password1` with `--expiration-in-days` (default **30**, allowed 1–90).
   Regenerating `password1` invalidates the previous one, so the same command rotates.
2. Builds the `dockerconfigjson` in memory and pipes it over stdin into
   `kubectl apply --server-side`. Nothing is printed or written to disk. Server-side apply also
   avoids the `last-applied-configuration` annotation, which would duplicate the secret.
   *Amended in phase 7:* `--stdin` accepts a password minted elsewhere. Run `az` on a
   workstation and pipe its output over `gh codespace ssh`, so the Codespace never holds an
   Azure login with registry rights. The script checks that the second line is a timestamp,
   so swapped input is rejected.
3. Annotates the Secret with the expiry (`healthqueue.io/credential-expires-at`).
   `create-pull-secret.sh status` reports the days left and warns under 7.

The `healthqueue-api` ServiceAccount references the Secret through `imagePullSecrets`. The Secret
is not in Git, so Argo CD neither tracks nor prunes it. `.gitignore` blocks the usual file names
as a second line of defence, and the CI secret scan is the third.

### Revocation

- **Normal:** PR setting `enabled = false` on the token. Every password stops working at once.
- **Break-glass:** `az acr token update -r crhealthqueueora3w -n kind-pull --status disabled`,
  then a PR that matches the code to it (the drift check flags the difference otherwise).

## What a production AKS cluster would use instead

**No pull secret at all.** On AKS:

- The **kubelet managed identity** (a user-assigned identity AKS creates for the node pools) gets
  `AcrPull` on the registry. Node-level image pulls authenticate with Entra ID tokens that the
  platform refreshes automatically: nothing to store, rotate or leak. In this repository that is
  one `azurerm_role_assignment` in `envs/prod`. `AcrPull` to a service principal is already
  within the apply identity's ABAC-constrained delegation (ADR-0003), so it would go through the
  normal PR flow.
- The AKS overlay would **remove `imagePullSecrets`** from the ServiceAccount and the cluster would
  never hold `acr-pull`.
- With Premium SKU (ADR-0003 roadmap), the registry would also sit behind a **private endpoint**
  reachable only from the cluster's virtual network.

**Workload Identity is a different thing.** It federates a *pod's* ServiceAccount to an Entra
identity so application code can call Azure APIs, e.g. PostgreSQL with Entra auth (ADR-0005).
Image pulls are done by the kubelet, not the pod, so Workload Identity does not replace the
kubelet identity.

## Consequences

**Positive**

- A leaked `acr-pull` credential exposes read access to one repository for at most 30 days,
  and one PR revokes it.
- No long-lived registry secret exists anywhere: not in Git, not in state, not on a laptop.
- The token and its scope are reviewed IaC; only the short-lived password is outside it.

**Negative / accepted risks**

- **Expiry is a scheduled outage if ignored.** Running pods keep running (the image is cached on
  the node), but rescheduled or new pods hit `ImagePullBackOff` once the password expires.
  Mitigations: the `status` subcommand, the expiry annotation (phase 10 can alert on it), and the
  [runbook](../runbooks/image-pull-failures.md).
- **The Secret sits in the kind cluster's etcd, base64-encoded, without encryption at rest.**
  That is acceptable for a disposable cluster holding a 30-day, read-only, single-repository
  credential.
- **Generating passwords needs rights on the registry** (Contributor or Owner). The CI apply
  identity technically has them (Contributor on the resource group) but never uses them; no
  workflow calls the generate API.
- **One manual step when creating a cluster.** It is documented in `deploy/README.md` and comes
  before the Argo CD sync (phase 7).

## Alternatives considered

| Option | Why rejected |
|---|---|
| ACR admin user | One shared username and password with **push and delete** on every repository, no expiry. Fails requirements 1 and 2. |
| Anonymous pull | Needs Standard SKU and makes every image public, including the application code inside it. |
| Service principal + client secret with `AcrPull` | Long-lived secret (up to 2 years), needs Entra app registration rights, and covers every repository in the registry. |
| `azurerm_container_registry_token_password` | Password lands in OpenTofu state, which PR plans can decrypt (requirement 3). |
| SOPS or Sealed Secrets in Git | The credential would sit in Git, encrypted, and need a decryption key managed in the cluster. That adds machinery for a secret that is cheaper to regenerate than to protect. |
| External Secrets Operator + Key Vault | ESO itself needs an Azure credential to read Key Vault. kind has no managed identity, so this moves the bootstrap secret rather than removing it. It is the right pattern on AKS for *application* secrets, combined with Workload Identity. |
| Mirror images to public GHCR | Makes images public and splits the audit trail away from Entra ID and the evidence store. |

## Revisit when

- The cluster moves to AKS: switch to the kubelet identity and remove `imagePullSecrets`.
- More than one cluster pulls with the token: rotate with alternating `password1`/`password2` so
  each cluster can be updated without a gap.
- Phase 10 exists: alert when `credential-expires-at` is under 7 days away.
