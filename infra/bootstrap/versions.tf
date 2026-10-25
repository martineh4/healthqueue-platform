terraform {
  required_version = ">= 1.10.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.9.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9.1"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.14.2"
    }
  }

  # No state encryption here, deliberately: this configuration creates the Key Vault
  # that encrypts every other state file, so encrypting its own state with that vault
  # would make the root of trust depend on itself. The state holds no usable secrets
  # (shared-key auth is disabled on the storage account) and is readable only by state
  # admins. See docs/adr/0002-opentofu-state-management.md.
}

provider "azurerm" {
  # Supplied via TF_VAR_subscription_id so it never lands in the repository. Not
  # ARM_SUBSCRIPTION_ID: the azure_vault key provider also reads that variable and then
  # asks the Azure CLI for a token with both subscription and tenant, which az >= 2.91 rejects.
  subscription_id = var.subscription_id
  # Data-plane calls (blob containers) use Entra ID, matching shared_access_key_enabled = false.
  storage_use_azuread = true

  resource_providers_to_register = [
    "Microsoft.KeyVault",
    "Microsoft.Storage",
  ]

  features {
    key_vault {
      # Never purge a soft-deleted vault or key on destroy: losing them means losing state.
      purge_soft_delete_on_destroy       = false
      purge_soft_deleted_keys_on_destroy = false
      recover_soft_deleted_key_vaults    = true
      recover_soft_deleted_keys          = true
    }
  }
}
