# Production environment for the HealthQueue appointment API.
# Phase 3 establishes the resource group on encrypted remote state; phase 4 adds the
# container registry, evidence storage, and the GitHub Actions workload identity.

resource "azurerm_resource_group" "prod" {
  name     = "rg-healthqueue-prod"
  location = var.location
  tags     = var.tags
}
