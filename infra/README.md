# Infrastructure (OpenTofu on Azure)

```
infra/
├── bootstrap/     # state storage, encryption keys, env resource groups, CI identities;
│                  # applied by a human, rarely
└── envs/
    └── prod/      # registry, evidence storage, release identity; applied by CI only
```

All resources live in `swedencentral` ([ADR-0001](../docs/adr/0001-azure-region-selection.md)).
State design and its trade-offs are in [ADR-0002](../docs/adr/0002-opentofu-state-management.md);
CI identities and their roles in [ADR-0003](../docs/adr/0003-github-actions-workload-identity.md).

## How state is handled

| | `bootstrap` | `envs/prod` |
|---|---|---|
| Backend | `azurerm`, blob `tfstate/bootstrap.tfstate` | `azurerm`, blob `tfstate-prod/prod.tfstate` |
| Locking | Blob lease | Blob lease |
| Client-side encryption | None (holds no usable secrets; see ADR-0002) | AES-GCM, data key wrapped by Key Vault key `tfstate-prod` |
| Who can read it | State admins (Storage Blob Data Contributor on the account) | State admins, plus the CI plan/apply identities: blob role on container `tfstate-prod` **and** Key Vault Crypto User on key `tfstate-prod` |
| Who applies it | A human state admin | CI only (`tofu-apply` job, `prod` GitHub environment) |
| Recovery | Blob versioning + 30-day soft delete | Same, plus key versions are retained after rotation |

The storage account accepts Entra ID tokens only (`shared_access_key_enabled = false`):
there are no account keys or SAS tokens to leak.

## Prerequisites

- OpenTofu >= 1.10 (the Codespace has it; `winget install OpenTofu.Tofu` on Windows)
- Azure CLI, logged in with `az login`
- **Do not set `ARM_SUBSCRIPTION_ID`.** Pass the subscription through a variable instead.
  The `azure_vault` key provider also reads `ARM_SUBSCRIPTION_ID` and then requests a CLI token
  for both subscription and tenant, which Azure CLI 2.91+ rejects with
  *"Please specify only one of subscription and tenant, not both"*.

```bash
export TF_VAR_subscription_id="$(az account show --query id -o tsv)"   # bash
$env:TF_VAR_subscription_id = az account show --query id -o tsv        # PowerShell
```

## Day-to-day (prod): pull requests

Changes to `envs/prod` go through a pull request ([`infra.yml`](../.github/workflows/infra.yml)):

| Event | Job | Identity | What happens |
|---|---|---|---|
| Any PR | `tofu-validate` (required) | none | `tofu fmt -check`, `init -backend=false`, `validate` for every root module |
| PR touching `infra/**` | `tofu-plan` (required) | `id-hq-tofu-prod-plan` (read-only) | Plan posted as a PR comment (IDs redacted), updated on each push |
| Merge to `main` | `tofu-apply` | `id-hq-tofu-prod-apply` via the `prod` environment | Re-plan under a state lock, then apply that exact plan |
| Daily 05:17 UTC | `tofu-drift` | plan identity | `plan -detailed-exitcode`; opens or comments on a `drift` issue if anything changed outside OpenTofu |

A local plan is still useful while writing a change; it uses your own state-admin access:

```bash
tofu -chdir=infra/envs/prod init
tofu -chdir=infra/envs/prod plan -lock=false
```

Local `apply` on prod is **break-glass only** (CI broken and production impaired). Afterwards,
open a PR that brings the code in line, so the next CI apply does not revert the fix.

### GitHub configuration (one-off, not in OpenTofu)

| Setting | Value |
|---|---|
| Environments | `prod` and `release`, deployments from protected branches only |
| Repository secrets | `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_CLIENT_ID_TOFU_PLAN` |
| `prod` environment secret | `AZURE_CLIENT_ID` (apply identity) |
| `release` environment secret | `AZURE_CLIENT_ID` (`release_client_id` output of envs/prod) |
| Label | `drift` |

Values come from `tofu -chdir=infra/bootstrap output -json github_oidc`. Set them with
`gh secret set NAME --body "$VALUE"` from bash. **Do not pipe values into `gh secret set` from
Windows PowerShell 5.1:** it prepends a byte-order mark, the secret becomes `﻿<guid>`,
Azure CLI rejects it, and GitHub's log masking no longer matches the real ID.

## Bootstrapping from scratch

Only needed for a brand-new subscription. The bootstrap creates the storage account that
its own state will live in, so the first apply runs with local state and then migrates.

1. Move the backend block aside: `mv infra/bootstrap/backend.tf infra/bootstrap/backend.tf.off`
2. `tofu -chdir=infra/bootstrap init && tofu -chdir=infra/bootstrap apply`
   (about 4 minutes; it waits 120 s for Key Vault RBAC to propagate before creating keys)
3. Put the new `storage_account_name` output into `backend.tf`, restore it, and run
   `tofu -chdir=infra/bootstrap init -migrate-state`
4. **Delete the local `terraform.tfstate` and `terraform.tfstate.backup`.** They are plaintext
   copies of the state.
5. Update the backend block and `vault_uri` in each `envs/*/versions.tf` with the new names.
6. Set the GitHub secrets listed above from the new `github_oidc` output.

### If key creation fails with 403

RBAC propagation took longer than 120 s. Run `tofu apply` again; nothing else is needed.

## Adding an environment

1. Add it to `environments` in `bootstrap/variables.tf` and apply the bootstrap. This creates its
   resource group, `tfstate-<env>` container, `tfstate-<env>` key, and plan/apply identities.
2. Copy `envs/prod` to `envs/<env>`; change `container_name`, `key` and `vault_key_name`.
3. Create the `<env>` GitHub environment with its `AZURE_CLIENT_ID` secret, and a job in
   `infra.yml` for it.

## Tearing down (end of course)

The state resource group is protected three ways on purpose: a `CanNotDelete` lock,
`prevent_destroy` on the account, vault and keys, and Key Vault purge protection.

1. Destroy environments first: `tofu -chdir=infra/envs/prod destroy`. The evidence container's
   immutability policy is unlocked, but blobs younger than its retention (7 days) cannot be
   deleted; wait, or delete the policy first in the portal.
2. Delete the lock: `az lock delete --name protect-tfstate --resource-group rg-healthqueue-tfstate`
3. Delete the group: `az group delete --name rg-healthqueue-tfstate`

The Key Vault then stays soft-deleted for 90 days and cannot be purged early. Soft-deleted
vaults are not billed, but the name `kv-hq-tfstate-prryv` stays reserved until then.
