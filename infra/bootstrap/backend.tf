# Where this configuration keeps its own state: the storage account it created. Access is by
# Entra ID identity (use_azuread_auth), never by a storage key.
#
# Added after the first apply, which ran with local state (the storage account did not
# exist yet), then migrated with `tofu init -migrate-state`. See README.md.
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-healthqueue-tfstate"
    storage_account_name = "sthqtfstateprryv"
    container_name       = "tfstate"
    key                  = "bootstrap.tfstate"
    use_azuread_auth     = true
  }
}
