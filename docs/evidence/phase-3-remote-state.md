# Evidence: Phase 3, remote state with locking and encryption

Captured 2026-10-25 from the live environment. Subscription and object IDs are redacted.

## 1. Bootstrap apply (state storage + encryption keys)

```
random_string.suffix: Creation complete after 0s [id=prryv]
azurerm_resource_group.state: Creation complete after 28s
azurerm_storage_account.state: Creation complete after 31s
azurerm_storage_container.state: Creation complete after 13s
azurerm_role_assignment.state_blob_admin["<object-id>"]: Creation complete after 41s
azurerm_management_lock.state: Creation complete after 2m20s
azurerm_key_vault.state: Creation complete after 2m47s
azurerm_role_assignment.state_key_admin["<object-id>"]: Creation complete after 38s
time_sleep.rbac_propagation: Creation complete after 2m0s
azurerm_key_vault_key.state["prod"]: Creation complete after 7s
Apply complete! Resources: 10 added, 0 changed, 0 destroyed.
```

## 2. Bootstrap state migrated from local to Azure

```
$ tofu -chdir=infra/bootstrap init -migrate-state -force-copy
Successfully configured the backend "azurerm"! ...

$ tofu -chdir=infra/bootstrap plan -detailed-exitcode
No changes. Your infrastructure matches the configuration.        (exit 0)
```

Local `terraform.tfstate`, `terraform.tfstate.backup`, and the saved plan were then deleted.

## 3. Prod environment on encrypted remote state

```
$ tofu -chdir=infra/envs/prod apply prod.tfplan
azurerm_resource_group.prod: Creation complete after 27s
Apply complete! Resources: 1 added, 0 changed, 0 destroyed.

$ az storage blob list --auth-mode login --account-name sthqtfstateprryv -c tfstate
bootstrap.tfstate
prod.tfstate
```

## 4. State is ciphertext at rest

Raw blob downloaded with `az storage blob download`, bypassing OpenTofu:

```
top-level keys: serial, lineage, meta, encrypted_data, encryption_version
encryption_version: v0
meta key providers: key_provider.azure_vault.prod
encrypted_data length: 1492 chars
contains 'rg-healthqueue-prod' in plaintext: False
contains 'resources' key in plaintext: False
```

Through OpenTofu, with Key Vault access, the same state decrypts normally:

```
$ tofu -chdir=infra/envs/prod state list
azurerm_resource_group.prod
```

## 5. Locking prevents concurrent runs

A 60-second lease was taken on `prod.tfstate` out-of-band (simulating another apply in progress),
then a plan was attempted:

```
$ az storage blob lease acquire ... -b prod.tfstate --lease-duration 60
lease acquired: True

$ tofu -chdir=infra/envs/prod plan -lock-timeout=0s
Error: Error acquiring the state lock
Error message: state blob is already locked

$ az storage blob lease release ...
lease released

$ tofu -chdir=infra/envs/prod plan -detailed-exitcode
No changes. Your infrastructure matches the configuration.
```

## 6. Provider supply chain

Provider versions are pinned (`azurerm ~> 5.9.0`, `random ~> 3.9.1`, `time ~> 0.14.2`), all
releases at least two weeks old when chosen. Signed by HashiCorp (key ID `0C0AF313E5FD9F80`), with
checksums for linux_amd64, windows_amd64, and darwin_arm64 committed in `.terraform.lock.hcl`.
