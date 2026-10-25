# ADR-0001: Azure region selection

- **Status:** Accepted
- **Date:** 2026-10-25
- **Deciders:** Platform engineering (lead DevOps engineer); informed: CTO
- **Related:** [Infrastructure as Code](../../infra/), future ADR on Kubernetes hosting

## Context

HealthQueue is a US health-tech company. Its appointment API will eventually process
protected health information (PHI) for US patients. Every Azure resource we provision
with OpenTofu (state storage, container registry, evidence storage, workload identity)
must be created in a single, deliberately chosen region.

Two forces pull in different directions:

1. **Where production should live.** For a US healthcare workload, the default expectation
   is a US region. HIPAA itself does not mandate US data residency, but in practice US
   healthcare companies keep PHI onshore because of customer and payer contracts, some state
   privacy laws, security questionnaires that ask for it, and lower latency to US patients.
   Microsoft offers a HIPAA Business Associate Agreement (BAA) for in-scope Azure services,
   so the BAA does not constrain the choice between US regions.
2. **Where this environment can live.** The reference environment runs on an Azure for
   Students subscription. That subscription has an enforced Azure Policy assignment,
   *Allowed resource deployment regions*, that permits only:
   `norwayeast`, `belgiumcentral`, `swedencentral`, `denmarkeast`, `francecentral`.
   Deployments to any other region are denied.

The policy is assigned at subscription scope, so the subscription Owner could technically
delete it. We will not: Microsoft applies it to manage capacity on the offer, and removing it
risks violating the offer terms or the policy being reapplied mid-project, which would leave
infrastructure in a region the platform can no longer manage.

## Decision

**The reference environment is deployed to `swedencentral`. A production deployment for
HealthQueue would use `eastus2` as the primary region, with `centralus` as the paired region
for disaster recovery.**

We implement this so the region is a single input, not a property of the code:

- OpenTofu exposes one `location` variable (default `swedencentral` in this environment).
  No module hardcodes a region.
- Resource names do not encode the region, so moving does not force renames beyond
  globally unique names that are already parameterised.

### Why `swedencentral` among the allowed regions

| Criterion | swedencentral | Others in the allowed list |
|---|---|---|
| Storage accounts, ACR, user-assigned managed identities available | Yes (verified via `az provider show`, 2026-10-25) | Yes for most; `belgiumcentral` and `denmarkeast` are newer regions with a smaller service catalogue |
| Availability zones | Yes | Varies |
| Azure positions it as a primary EU region with broad service rollout | Yes | `norwayeast` and `francecentral` are comparable; no strong reason to prefer them |

Any of `swedencentral`, `norwayeast`, or `francecentral` would have been acceptable. We chose
`swedencentral` for its broad, early service availability, which reduces the chance a later
phase needs a service the region lacks.

### Why `eastus2` for production

Large capacity, availability zones, broad service availability, and a defined regional pair
(`centralus`) for geo-redundant storage and DR. Final production region selection should be
re-confirmed with Legal/Compliance against HealthQueue's customer contracts before launch.

## Consequences

**Positive**

- The platform deploys successfully within the subscription's guardrails, with no policy
  exceptions and no risk to the subscription.
- Region is a parameter. Re-homing to `eastus2` is a variable change plus re-provisioning;
  it is an operational task, not a redesign.
- The decision and the production target are explicit, so nobody mistakes the reference
  environment's region for the production design.

**Negative / accepted risks**

- **Residency gap.** This environment does not match the production residency intent.
  Accepted because it holds **no PHI**: all data is synthetic (see `dora/` and test
  fixtures), and the API's demo database runs inside the Kubernetes cluster, not in Azure.
- **Transatlantic hop.** Image pulls from the registry in Sweden to a cluster in a US-hosted
  Codespace add latency at deploy time. It does not affect request latency or the API's
  latency SLO, because the registry is not on the request path.
- **Migration is not free.** State storage cannot be moved in place; moving regions means
  creating a new state account, migrating state (`tofu init -migrate-state`), and recreating
  region-bound resources (registry, storage). Images would be re-pushed from CI; evidence
  archives would be copied with `azcopy`.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Delete or exempt the region policy and use `eastus2` now | Works against the subscription offer's guardrails; risk of the policy being reapplied and stranding resources. A policy exemption is also an Owner-level change we cannot justify for a non-production environment. |
| Separate pay-as-you-go subscription in a US region | Matches production intent but incurs direct cost for a reference environment holding no PHI. Revisit when the platform moves to a company-owned subscription. |
| Multi-region from day one | Doubles cost and complexity before there is any traffic; DR design belongs with the production subscription. |

## Revisit when

- HealthQueue moves to a company-owned (non-student) subscription, or
- Any real PHI is introduced into an environment provisioned from this repository.
