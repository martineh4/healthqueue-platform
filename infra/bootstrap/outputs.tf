# Values other configurations and people need after the bootstrap: where state lives and
# which identities CI should log in as.

output "resource_group_name" {
  value = azurerm_resource_group.state.name
}

output "storage_account_name" {
  value = azurerm_storage_account.state.name
}

output "container_name" {
  value = azurerm_storage_container.state.name
}

output "key_vault_uri" {
  value = azurerm_key_vault.state.vault_uri
}

output "state_key_names" {
  description = "Key Vault key name per environment, for the environment's encryption block."
  value       = { for env, key in azurerm_key_vault_key.state : env => key.name }
}

output "backend_config" {
  description = "Values for each environment's azurerm backend block."
  value = {
    resource_group_name  = azurerm_resource_group.state.name
    storage_account_name = azurerm_storage_account.state.name
    container_name       = azurerm_storage_container.state.name
    use_azuread_auth     = true
  }
}

output "environment_state" {
  description = "Per-environment backend container and encryption key name."
  value = { for env in local.envs : env => {
    container_name = azurerm_storage_container.env_state[env].name
    key_name       = azurerm_key_vault_key.state[env].name
    resource_group = azurerm_resource_group.env[env].name
  } }
}

output "github_oidc" {
  description = <<-EOT
    Client IDs for azure/login. Not secrets (a federated credential is what grants access),
    but stored as GitHub secrets anyway so the public workflow logs stay free of IDs.
  EOT
  value = {
    tenant_id = data.azurerm_client_config.current.tenant_id
    environments = { for env in local.envs : env => {
      plan_client_id  = azurerm_user_assigned_identity.plan[env].client_id
      apply_client_id = azurerm_user_assigned_identity.apply[env].client_id
    } }
  }
  sensitive = true
}
