# Production environment for the HealthQueue appointment API.
#
# The resource group itself belongs to the bootstrap (it grants CI identities their roles
# on it); this configuration manages what goes inside it and runs as the CI apply identity.
#
# In plain terms, three things live here:
#   - a private container registry, where released application images are stored;
#   - write-once evidence storage, the release audit trail (scan reports, ingredient lists,
#     signatures), which cannot be edited or deleted during its retention period;
#   - the identities and permissions that let the release pipeline and the cluster use them,
#     each limited to exactly what it needs.

data "azurerm_resource_group" "prod" {
  name = "rg-healthqueue-prod"
}

# Registry and storage names must be unique across all of Azure: a random suffix, kept in state.
resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  rg       = data.azurerm_resource_group.prod
  suffix   = random_string.suffix.result
  location = local.rg.location
}

# ---------------------------------------------------------------------------
# Container registry
# ---------------------------------------------------------------------------

# Basic SKU: private endpoints, retention policies and content trust need Premium
# (~$50/month), out of scope for a student subscription. Images are signed with cosign
# and verified by digest instead of relying on registry-side features. See ADR-0003.
resource "azurerm_container_registry" "main" {
  name                = "crhealthqueue${local.suffix}"
  resource_group_name = local.rg.name
  location            = local.location
  sku                 = "Basic"

  admin_enabled = false # Entra ID tokens only; no shared username/password
  tags          = var.tags
}

# ---------------------------------------------------------------------------
# Release evidence (SBOMs, scan reports, provenance), write-once
# ---------------------------------------------------------------------------

# Accepted risk (ADR-0002): public endpoint with RBAC as the boundary, because
# GitHub-hosted runners have no fixed IPs. Expiry forces a review.
#trivy:ignore:AZU-0012:exp:2027-04-30
resource "azurerm_storage_account" "evidence" {
  name                = "sthqevidence${local.suffix}"
  resource_group_name = local.rg.name
  location            = local.location

  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "ZRS"

  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  local_user_enabled                = false
  sftp_enabled                      = false
  cross_tenant_replication_enabled  = false
  https_traffic_only_enabled        = true
  min_tls_version                   = "TLS1_2"
  infrastructure_encryption_enabled = true
  public_network_access             = "Enabled"

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }
    container_delete_retention_policy {
      days = 30
    }
  }

  tags = var.tags
}

resource "azurerm_storage_container" "evidence" {
  name                  = "release-evidence"
  storage_account_id    = azurerm_storage_account.evidence.id
  container_access_type = "private"
}

# WORM: once written, release evidence cannot be modified or deleted for the retention
# period, not even by the release identity that wrote it. Unlocked with a short period so
# the course environment can be torn down; production would lock it at 2190 days (six
# years, the HIPAA documentation retention period). See ADR-0003.
resource "azurerm_storage_container_immutability_policy" "evidence" {
  storage_container_resource_manager_id = azurerm_storage_container.evidence.id
  immutability_period_in_days           = var.evidence_retention_days
  locked                                = false
}

# ---------------------------------------------------------------------------
# Release identity: used by the release workflow (phase 5) from the `release`
# GitHub environment to push images and upload evidence
# ---------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "release" {
  name                = "id-hq-release"
  resource_group_name = local.rg.name
  location            = local.location
  tags                = var.tags
}

resource "azurerm_federated_identity_credential" "release" {
  name                      = "github-environment-release"
  user_assigned_identity_id = azurerm_user_assigned_identity.release.id
  issuer                    = "https://token.actions.githubusercontent.com"
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "${var.github_oidc_subject_prefix}:environment:release"
}

# principal_type is required: the apply identity's role-assignment rights are
# conditioned on PrincipalType == ServicePrincipal.
resource "azurerm_role_assignment" "release_acr_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.release.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "release_evidence_write" {
  scope                = azurerm_storage_container.evidence.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.release.principal_id
  principal_type       = "ServicePrincipal"
}

# ---------------------------------------------------------------------------
# Pull-only registry token for the kind cluster (ADR-0004)
# ---------------------------------------------------------------------------

# Read access to one repository, nothing else: no push, no delete, no other repositories.
# metadata/read lets clients list tags and referrers (signatures, attestations), which
# signature verification at admission will need (phase 9, deferred).
resource "azurerm_container_registry_scope_map" "api_pull" {
  name                    = "healthqueue-api-pull"
  description             = "Pull healthqueue-api images and their signatures. Nothing else."
  container_registry_name = azurerm_container_registry.main.name
  resource_group_name     = local.rg.name
  actions = [
    "repositories/healthqueue-api/content/read",
    "repositories/healthqueue-api/metadata/read",
  ]
}

# Deliberately no azurerm_container_registry_token_password: a password resource would put
# the secret in state, which the PR plan identity can decrypt. Passwords are generated with
# an expiry, at the moment they are needed, by deploy/scripts/create-pull-secret.sh, and go
# straight into the cluster. Setting enabled = false here revokes every password at once.
resource "azurerm_container_registry_token" "kind_pull" {
  name                    = "kind-pull"
  container_registry_name = azurerm_container_registry.main.name
  resource_group_name     = local.rg.name
  scope_map_id            = azurerm_container_registry_scope_map.api_pull.id
  enabled                 = true
}
