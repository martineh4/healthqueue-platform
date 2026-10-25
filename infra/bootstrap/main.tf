# Foundation for all other OpenTofu configurations in this repository:
#   - a locked resource group
#   - a storage account + container holding every state file (Entra ID auth only)
#   - a Key Vault with one RSA key per environment, used by OpenTofu's `azure_vault`
#     key provider to encrypt that environment's state client-side

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  suffix    = random_string.suffix.result
  admin_ids = toset(concat([data.azurerm_client_config.current.object_id], var.state_admin_object_ids))
}

resource "azurerm_resource_group" "state" {
  name     = "rg-healthqueue-tfstate"
  location = var.location
  tags     = var.tags
}

# Deleting this resource group would orphan every environment, so it is locked.
# To tear down deliberately: remove this resource from config, apply, then destroy.
resource "azurerm_management_lock" "state" {
  name       = "protect-tfstate"
  scope      = azurerm_resource_group.state.id
  lock_level = "CanNotDelete"
  notes      = "Holds OpenTofu state and its encryption keys for all HealthQueue environments."
}

# ---------------------------------------------------------------------------
# State storage
# ---------------------------------------------------------------------------

resource "azurerm_storage_account" "state" {
  name                = "sthqtfstate${local.suffix}"
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location

  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "ZRS" # survives a zone outage in swedencentral

  # Identity-based access only: no account keys, no SAS, no anonymous reads.
  shared_access_key_enabled         = false
  default_to_oauth_authentication   = true
  allow_nested_items_to_be_public   = false
  local_user_enabled                = false
  sftp_enabled                      = false
  cross_tenant_replication_enabled  = false
  https_traffic_only_enabled        = true
  min_tls_version                   = "TLS1_2"
  infrastructure_encryption_enabled = true

  # GitHub-hosted runners have no fixed IP range, so the endpoint stays public and
  # access is enforced by Entra ID RBAC. Revisit with self-hosted runners + private endpoint.
  public_network_access = "Enabled"

  blob_properties {
    versioning_enabled = true # every state write is a recoverable version

    delete_retention_policy {
      days = 30
    }
    container_delete_retention_policy {
      days = 30
    }
  }

  tags = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "state_blob_admin" {
  for_each             = local.admin_ids
  scope                = azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}

# ---------------------------------------------------------------------------
# State encryption keys
# ---------------------------------------------------------------------------

resource "azurerm_key_vault" "state" {
  name                = "kv-hq-tfstate-${local.suffix}"
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  rbac_authorization_enabled = true
  # Losing this vault makes every encrypted state file unreadable, so deletion is
  # recoverable for 90 days and cannot be short-circuited by a purge.
  purge_protection_enabled   = true
  soft_delete_retention_days = 90

  # Same reasoning as the storage account: RBAC is the boundary, not the network.
  public_network_access_enabled = true

  tags = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_role_assignment" "state_key_admin" {
  for_each             = local.admin_ids
  scope                = azurerm_key_vault.state.id
  role_definition_name = "Key Vault Crypto Officer"
  principal_id         = each.value
}

# Azure RBAC assignments take a short while to reach the Key Vault data plane;
# creating keys immediately after the assignment fails with 403.
resource "time_sleep" "rbac_propagation" {
  create_duration = "120s"
  triggers = {
    assignments = join(",", [for a in azurerm_role_assignment.state_key_admin : a.id])
  }
}

# One key per state file, as recommended by the OpenTofu encryption docs, so access
# to one environment's state can be granted or revoked independently.
resource "azurerm_key_vault_key" "state" {
  for_each     = toset(sort(tolist(var.environments)))
  name         = "tfstate-${each.key}"
  key_vault_id = azurerm_key_vault.state.id
  key_type     = "RSA"
  key_size     = 3072
  key_opts     = ["encrypt", "decrypt"] # all OpenTofu's azure_vault provider needs

  # Rotation creates a new key version for future writes; OpenTofu records the version
  # used for each state write, so older states stay decryptable after rotation.
  rotation_policy {
    automatic {
      time_after_creation = "P365D"
    }
  }

  tags = var.tags

  depends_on = [time_sleep.rbac_propagation]

  lifecycle {
    prevent_destroy = true
  }
}
