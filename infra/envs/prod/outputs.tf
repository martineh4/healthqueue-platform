# Names the release workflow and deploy scripts need. The client ID is marked sensitive only
# to keep it out of logs; it is not a credential.

output "resource_group_name" {
  value = local.rg.name
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "evidence_storage_account" {
  value = azurerm_storage_account.evidence.name
}

output "evidence_container" {
  value = azurerm_storage_container.evidence.name
}

output "release_client_id" {
  description = "Client ID for azure/login in the release workflow. Stored as a GitHub secret."
  value       = azurerm_user_assigned_identity.release.client_id
  sensitive   = true
}

output "kind_pull_token_name" {
  description = "ACR token used by deploy/scripts/create-pull-secret.sh. The token has no stored password."
  value       = azurerm_container_registry_token.kind_pull.name
}
