# ADR-0002: OpenTofu state management

- **Status:** Accepted
- **Date:** 2026-10-25
- **Deciders:** Platform engineering; informed: CTO
- **Related:** [ADR-0001](0001-azure-region-selection.md), [`infra/README.md`](../../infra/README.md)

## Context

OpenTofu state is the source of truth for what infrastructure exists. It also routinely contains
sensitive values: resource IDs, connection strings, and sometimes keys returned by cloud APIs.
Whoever can read state learns the shape of our estate. Whoever can **write** it can make the next
apply destroy or re-point production.

Requirements:

1. **Shared and durable.** CI and engineers must use the same state. It must survive a laptop
   loss and be recoverable after accidental corruption.
2. **Concurrency-safe.** Two applies at once (CI and a human, or two merged PRs) must not
   interleave writes.
3. **Confidential.** Reading state must need an explicit, auditable grant, not just network
   reachability or a shared key.
4. **No long-lived secrets.** We do not want a state passphrase or storage key that has to be
   copied into GitHub, onto laptops, and into a password manager.
5. **Recoverable root of trust.** Whatever protects state must not be able to lock us out of the
   means to rebuild it.

## Decision

### Storage and locking

- State for every configuration lives in **one Azure Storage account** (`sthqtfstate…`) in the
  `rg-healthqueue-tfstate` resource group, one blob per configuration.
- The `azurerm` backend uses **blob leases** for locking. A held lease makes any other
  `plan`/`apply` fail fast with *"state blob is already locked"*.
- **Entra ID only:** shared-key and SAS access are disabled on the account. Access is granted
  with `Storage Blob Data Contributor`, so it is per-identity, revocable, and visible in the
  activity log.
- **Recovery:** blob versioning (every write is a version), 30-day blob and container soft
  delete, ZRS replication, a `CanNotDelete` lock on the resource group, and `prevent_destroy`
  on the account.

### Encryption

- **Environment state (`envs/*`) uses OpenTofu client-side state and plan encryption** with the
  `azure_vault` key provider and `aes_gcm`. OpenTofu generates a fresh data key for each write
  and has Key Vault encrypt it with an RSA-3072 key that never leaves the vault. `enforced = true`
  makes OpenTofu refuse to read or write plaintext state.
- **One key per state file** (`tfstate-prod`, later `tfstate-staging`), following the OpenTofu
  docs. Reading an environment's state therefore needs **two independent grants**: blob access
  *and* `Key Vault Crypto User` on that environment's key.
- **Key rotation:** automatic yearly. OpenTofu records the key version used for each write, so
  rotation never strands older state.
- **Vault protection:** purge protection with 90-day soft-delete retention. A deleted vault can
  always be recovered, and no one can short-circuit that with a purge.

### The bootstrap exception

The `bootstrap` configuration creates the storage account and the Key Vault. **Its own state is
not client-side encrypted.** We accept this deliberately:

- Encrypting it with the vault it manages is circular. If the vault were damaged, the state
  needed to repair the vault would be unreadable. That breaks requirement 5.
- The first apply necessarily runs before any vault exists, so encryption would need a
  multi-step plaintext-to-encrypted migration for little gain.
- The state contains **no usable secrets**. Storage account keys may appear in it, but shared-key
  auth is disabled, so the keys authenticate nothing. The state is still protected by Entra ID
  RBAC, versioning, and server-side encryption at rest (with infrastructure double encryption).

## Consequences

**Positive**

- Requirements 1–5 are met with no shared secret anywhere. CI (phase 4) authenticates with GitHub
  OIDC to a managed identity, which gets narrowly scoped roles on the container and its key.
- A leaked copy of `prod.tfstate` (backup, laptop, log) is ciphertext without Key Vault access.
- The plan file is also encrypted, closing the common leak where saved plans are uploaded as
  CI artifacts.

**Negative / accepted risks**

- **Key Vault is now on the critical path** for every `plan`/`apply`. A regional Key Vault outage
  blocks infrastructure changes (not the running application). Accepted for a change-control
  path. Key Vault's SLA is 99.99%.
- **Operational sharp edges.** The `azure_vault` key provider reads `ARM_SUBSCRIPTION_ID` and
  then fails with Azure CLI 2.91+ (*"specify only one of subscription and tenant"*). We pass the
  subscription as `TF_VAR_subscription_id` instead, documented in `infra/README.md`.
- **Teardown friction.** The lock, `prevent_destroy`, and purge protection make deleting the state
  layer deliberate and multi-step. That friction is intended.
- **Public endpoints.** Storage and Key Vault endpoints are publicly reachable because
  GitHub-hosted runners have no fixed IPs. RBAC, not the network, is the boundary. A production
  hardening step is self-hosted runners with private endpoints. The CI misconfiguration scan
  flags this as CRITICAL (Trivy AZU-0012, AZU-0013). We accept it with inline suppressions that
  **expire on 2027-04-30**, so the pipeline fails again on that date and forces a re-review
  instead of the exception living forever. The alternative, CI adding its runner IP to the
  firewall on every run, was rejected: concurrent runs race on the rules, and the CI identity
  would need network-admin rights on the state account.
- **No vault audit logs yet.** Key Vault diagnostic logs are not shipped anywhere until a Log
  Analytics workspace exists (observability phase).

## Alternatives considered

| Option | Why rejected |
|---|---|
| Local state committed to git | No locking, secrets in history, no shared source of truth. |
| Passphrase-based encryption (`pbkdf2`) | Introduces a long-lived shared secret that must be distributed to CI and humans; leak or loss is catastrophic and silent. |
| No client-side encryption, rely on Azure server-side encryption | Protects disks, not readers: anyone with blob read sees plaintext. Fails requirement 3 for any accidental copy. |
| Encrypt bootstrap state with the vault it creates | Circular dependency (see above). |
| Terraform Cloud / HCP for state | Adds a third-party SaaS and account to a regulated estate; OpenTofu-native encryption isn't available there. |
| One storage account per environment | Stronger blast-radius isolation, but per-environment keys already give separate read grants. Revisit if environments move to separate subscriptions. |

## Revisit when

- Environments move to separate subscriptions (consider a state account per subscription).
- Self-hosted runners exist (move storage and Key Vault behind private endpoints).
- The `azure_vault` key provider / Azure CLI interaction is fixed upstream (return to `ARM_*` env vars).
