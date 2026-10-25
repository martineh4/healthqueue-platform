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
