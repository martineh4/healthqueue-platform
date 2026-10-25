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
  }

  # Remote state in the bootstrap storage account, in a container that holds only this
  # environment's state, so CI identities can be granted access to exactly one state file.
  # Locking uses blob leases: two concurrent applies cannot corrupt state.
  backend "azurerm" {
    resource_group_name  = "rg-healthqueue-tfstate"
    storage_account_name = "sthqtfstateprryv"
    container_name       = "tfstate-prod"
    key                  = "prod.tfstate"
    use_azuread_auth     = true
  }

  # Client-side encryption of state and plan files. A fresh data key encrypts each write;
  # that data key is itself encrypted by the `tfstate-prod` RSA key in Key Vault, which
  # never leaves the vault. Reading state therefore needs both blob access AND
  # Key Vault Crypto User on this key: two independent RBAC grants.
  encryption {
    key_provider "azure_vault" "prod" {
      vault_uri      = "https://kv-hq-tfstate-prryv.vault.azure.net/"
      vault_key_name = "tfstate-prod"
      key_length     = 32
    }

    method "aes_gcm" "prod" {
      keys = key_provider.azure_vault.prod
    }

    state {
      method   = method.aes_gcm.prod
      enforced = true # refuse to write or read unencrypted state
    }

    plan {
      method   = method.aes_gcm.prod
      enforced = true
    }
  }
}

provider "azurerm" {
  # Supplied via TF_VAR_subscription_id so it never lands in the repository. Not
  # ARM_SUBSCRIPTION_ID: the azure_vault key provider also reads that variable and then
  # asks the Azure CLI for a token with both subscription and tenant, which az >= 2.91 rejects.
  subscription_id     = var.subscription_id
  storage_use_azuread = true

  # No resource provider registration (the 5.x default): that needs subscription-level
  # rights, which the CI identities deliberately lack. The bootstrap registers them.

  features {}
}
