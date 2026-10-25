# Infrastructure (OpenTofu on Azure)

```
infra/
├── bootstrap/     # state storage + encryption keys; applied by a human, rarely
└── envs/
    └── prod/      # application infrastructure; applied by CI from phase 4 onwards
```

All resources live in `swedencentral` ([ADR-0001](../docs/adr/0001-azure-region-selection.md)).
State design and its trade-offs are in [ADR-0002](../docs/adr/0002-opentofu-state-management.md).

## How state is handled

| | `bootstrap` | `envs/prod` |
|---|---|---|
| Backend | `azurerm`, blob `tfstate/bootstrap.tfstate` | `azurerm`, blob `tfstate/prod.tfstate` |
| Locking | Blob lease | Blob lease |
| Client-side encryption | None (holds no usable secrets; see ADR-0002) | AES-GCM, data key wrapped by Key Vault key `tfstate-prod` |
| Who can read it | Storage Blob Data Contributor on the account | Blob access **and** Key Vault Crypto User on `tfstate-prod` |
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

## Day-to-day (prod)

```bash
tofu -chdir=infra/envs/prod init
tofu -chdir=infra/envs/prod plan
```

From phase 4, changes to `envs/prod` go through a pull request: CI posts the plan as a PR
comment and applies on merge. Local applies are for break-glass only.

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

### If key creation fails with 403

RBAC propagation took longer than 120 s. Run `tofu apply` again; nothing else is needed.

## Adding an environment

1. Add it to `environments` in `bootstrap/variables.tf` and apply the bootstrap. This creates its
   own `tfstate-<env>` key: one key per state file, so access is granted per environment.
2. Copy `envs/prod` to `envs/<env>` and change `key` in the backend block and `vault_key_name`.

## Tearing down (end of course)

The state resource group is protected three ways on purpose: a `CanNotDelete` lock,
`prevent_destroy` on the account, vault and keys, and Key Vault purge protection.

1. Destroy environments first: `tofu -chdir=infra/envs/prod destroy`
2. Delete the lock: `az lock delete --name protect-tfstate --resource-group rg-healthqueue-tfstate`
3. Delete the group: `az group delete --name rg-healthqueue-tfstate`

The Key Vault then stays soft-deleted for 90 days and cannot be purged early. Soft-deleted
vaults are not billed, but the name `kv-hq-tfstate-prryv` stays reserved until then.
