# Evidence: Phase 4, PR-driven infrastructure delivery with GitHub OIDC

Captured 2026-10-25 from the live environment. Subscription, tenant, object and client IDs
are redacted. Design: [ADR-0003](../adr/0003-github-actions-workload-identity.md).

## 1. Bootstrap: landing zone and CI identities (applied by a state admin)

```
azurerm_resource_group.env["prod"]: Import complete
azurerm_storage_container.env_state["prod"]: Creation complete after 15s
azurerm_user_assigned_identity.plan["prod"]: Creation complete after 38s
azurerm_user_assigned_identity.apply["prod"]: Creation complete after 36s
azurerm_federated_identity_credential.plan_pr["prod"]: Creation complete after 33s
azurerm_federated_identity_credential.plan_main["prod"]: Creation complete after 33s
azurerm_federated_identity_credential.apply_env["prod"]: Creation complete after 34s
azurerm_role_assignment.plan_reader["prod"]: Creation complete after 33s
azurerm_role_assignment.plan_state_read["prod"]: Creation complete after 33s
azurerm_role_assignment.plan_state_key["prod"]: Creation complete after 35s
azurerm_role_assignment.apply_contributor["prod"]: Creation complete after 35s
azurerm_role_assignment.apply_rbac_delegate["prod"]: Creation complete after 50s
azurerm_role_assignment.apply_state_write["prod"]: Creation complete after 35s
azurerm_role_assignment.apply_state_key["prod"]: Creation complete after 33s
Apply complete! Resources: 1 imported, 13 added, 0 changed, 0 destroyed.

$ tofu -chdir=infra/bootstrap plan -detailed-exitcode
No changes. Your infrastructure matches the configuration.        (exit 0)
```

The import changed nothing on the resource group: the environment tags computed by the
bootstrap matched the ones `envs/prod` had set.

## 2. Prod state moved to its own container, still encrypted

```
$ tofu -chdir=infra/envs/prod init -migrate-state -force-copy
Successfully configured the backend "azurerm"!

$ az storage blob list --container-name tfstate-prod ...
prod.tfstate   2543 bytes

top-level keys of the raw blob: serial, lineage, meta, encrypted_data, encryption_version
plaintext "rg-healthqueue" present in blob: False
```

The old `tfstate/prod.tfstate` blob was then deleted. Versioning and soft delete keep it
recoverable for 30 days.

## 3. Pull request #4: plan as the read-only identity

The `tofu-plan` job authenticated as `id-hq-tofu-prod-plan` over OIDC and posted:

> :white_check_mark: Plan: 9 to add, 0 to change, 0 to destroy, 1 to forget.

The plan matched the local plan. The comment contains no GUIDs (all are redacted), and the job
log contains no raw subscription ID.

**Incident during this PR (fixed).** The first run failed with
`the provided subscription ID "﻿<subscription-id>" is not known by Azure CLI`. The secrets
had been piped into `gh secret set` from Windows PowerShell 5.1, which prepends a byte-order
mark. Because the stored value never appeared verbatim, GitHub's log masking and the
comment's exact-match redaction both missed the real ID.

Response:
1. Re-set all secrets from bash with `--body`, validating each as a bare GUID.
2. Deleted the run's logs and the PR comment.
3. Changed `plan-comment.sh` to redact every GUID as a backstop.
4. Documented the pitfall in `infra/README.md`.

The subscription ID is an identifier, not a credential, so no access was exposed.

## 4. Merge: apply as the apply identity

PR #4 was merged to `main`. The `tofu-apply` job ran in the `prod` GitHub environment as
`id-hq-tofu-prod-apply`:

```
changes: success
tofu-validate: success
tofu-apply: success
```

Resources now in `rg-healthqueue-prod`:

```
crhealthqueueora3w   Microsoft.ContainerRegistry/registries   (Basic, admin disabled)
sthqevidenceora3w    Microsoft.Storage/storageAccounts
id-hq-release        Microsoft.ManagedIdentity/userAssignedIdentities
```

Role assignments created **by CI** for the release identity. Both succeeded only because the
apply identity's conditioned RBAC Administrator role permits these two roles:

```
AcrPush                         registries/crhealthqueueora3w
Storage Blob Data Contributor   storageAccounts/sthqevidenceora3w/.../containers/release-evidence
```

Evidence container immutability policy:

```
immutabilityPeriodSinceCreationInDays: 7    state: Unlocked
```

A post-apply local plan reported `No changes` (exit 0).

## 5. Not yet demonstrated

- **Negative tests of the role delegation.** These would show that the apply identity is refused
  when it tries to assign `Owner`, or any role to a user. The condition is checked by design
  review and by the positive case above only.
**Since demonstrated.** The drift job was dispatched manually on `main` (run 40170264122).
`tofu-drift` succeeded as the plan identity, using the `ref:refs/heads/main` federated
credential. It found no drift and opened no issue.
