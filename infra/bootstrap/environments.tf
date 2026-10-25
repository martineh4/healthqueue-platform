# Per-environment landing zone: everything an environment's CI pipeline needs before it
# can manage itself, and nothing it should be able to change about its own permissions.
#
#   rg-healthqueue-<env>          resource group the environment configuration manages
#   tfstate-<env> container       that environment's state, nothing else
#   id-hq-tofu-<env>-plan         PR plans and drift checks: read-only everywhere
#   id-hq-tofu-<env>-apply        applies from the protected `<env>` GitHub environment
#
# The identities live in the state resource group, not the environment's, so the apply
# identity (Contributor on the environment group) cannot edit its own federated credentials.
# See docs/adr/0003-github-actions-workload-identity.md.

locals {
  envs = toset(sort(tolist(var.environments)))

  # Environment resource groups carry the environment tags, not `component = tfstate`.
  env_tags = { for env in local.envs : env => merge(
    { for k, v in var.tags : k => v if k != "component" },
    { environment = env },
  ) }

  oidc_issuer   = "https://token.actions.githubusercontent.com"
  oidc_audience = ["api://AzureADTokenExchange"]
}

resource "azurerm_resource_group" "env" {
  for_each = local.envs
  name     = "rg-healthqueue-${each.key}"
  location = var.location
  tags     = local.env_tags[each.key]
}

resource "azurerm_storage_container" "env_state" {
  for_each              = local.envs
  name                  = "tfstate-${each.key}"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
}

# ---------------------------------------------------------------------------
# Plan identity: pull requests and the scheduled drift check
# ---------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "plan" {
  for_each            = local.envs
  name                = "id-hq-tofu-${each.key}-plan"
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  tags                = var.tags
}

# Fork PRs never receive an OIDC token, so this subject only matches PRs from branches
# of this repository, i.e. from people with write access.
resource "azurerm_federated_identity_credential" "plan_pr" {
  for_each                  = local.envs
  name                      = "github-pull-request"
  user_assigned_identity_id = azurerm_user_assigned_identity.plan[each.key].id
  issuer                    = local.oidc_issuer
  audience                  = local.oidc_audience
  subject                   = "${var.github_oidc_subject_prefix}:pull_request"
}

resource "azurerm_federated_identity_credential" "plan_main" {
  for_each                  = local.envs
  name                      = "github-main-branch"
  user_assigned_identity_id = azurerm_user_assigned_identity.plan[each.key].id
  issuer                    = local.oidc_issuer
  audience                  = local.oidc_audience
  subject                   = "${var.github_oidc_subject_prefix}:ref:refs/heads/main"

  # Azure rejects concurrent credential writes on the same identity.
  depends_on = [azurerm_federated_identity_credential.plan_pr]
}

resource "azurerm_role_assignment" "plan_reader" {
  for_each             = local.envs
  scope                = azurerm_resource_group.env[each.key].id
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.plan[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

# Read-only on state: PR plans run with -lock=false because taking a lease is a write.
# The apply job re-plans under a lock, so a stale PR plan can never be applied.
resource "azurerm_role_assignment" "plan_state_read" {
  for_each             = local.envs
  scope                = azurerm_storage_container.env_state[each.key].id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.plan[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "plan_state_key" {
  for_each             = local.envs
  scope                = azurerm_key_vault_key.state[each.key].resource_versionless_id
  role_definition_name = "Key Vault Crypto User"
  principal_id         = azurerm_user_assigned_identity.plan[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

# ---------------------------------------------------------------------------
# Apply identity: only from the `<env>` GitHub environment (restricted to main)
# ---------------------------------------------------------------------------

resource "azurerm_user_assigned_identity" "apply" {
  for_each            = local.envs
  name                = "id-hq-tofu-${each.key}-apply"
  resource_group_name = azurerm_resource_group.state.name
  location            = azurerm_resource_group.state.location
  tags                = var.tags
}

resource "azurerm_federated_identity_credential" "apply_env" {
  for_each                  = local.envs
  name                      = "github-environment-${each.key}"
  user_assigned_identity_id = azurerm_user_assigned_identity.apply[each.key].id
  issuer                    = local.oidc_issuer
  audience                  = local.oidc_audience
  subject                   = "${var.github_oidc_subject_prefix}:environment:${each.key}"
}

resource "azurerm_role_assignment" "apply_contributor" {
  for_each             = local.envs
  scope                = azurerm_resource_group.env[each.key].id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.apply[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

# The environment grants its workloads data-plane roles (e.g. AcrPush for the release
# pipeline). Rather than User Access Administrator, the apply identity may create or delete
# assignments only for these roles, only for service principals, only in its own group.
data "azurerm_role_definition" "delegable" {
  for_each = toset(["AcrPull", "AcrPush", "Storage Blob Data Contributor"])
  name     = each.key
}

locals {
  delegable_role_ids = join(", ", sort([
    for r in data.azurerm_role_definition.delegable : basename(r.role_definition_id)
  ]))
}

resource "azurerm_role_assignment" "apply_rbac_delegate" {
  for_each             = local.envs
  scope                = azurerm_resource_group.env[each.key].id
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azurerm_user_assigned_identity.apply[each.key].principal_id
  principal_type       = "ServicePrincipal"
  description          = "Assign/remove AcrPull, AcrPush, Storage Blob Data Contributor to service principals only."
  condition_version    = "2.0"
  condition            = <<-EOT
    (
     (
      !(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})
     )
     OR
     (
      @Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.delegable_role_ids}}
      AND
      @Request[Microsoft.Authorization/roleAssignments:PrincipalType] ForAnyOfAnyValues:StringEqualsIgnoreCase {'ServicePrincipal'}
     )
    )
    AND
    (
     (
      !(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})
     )
     OR
     (
      @Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.delegable_role_ids}}
     )
    )
  EOT
}

resource "azurerm_role_assignment" "apply_state_write" {
  for_each             = local.envs
  scope                = azurerm_storage_container.env_state[each.key].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.apply[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "apply_state_key" {
  for_each             = local.envs
  scope                = azurerm_key_vault_key.state[each.key].resource_versionless_id
  role_definition_name = "Key Vault Crypto User"
  principal_id         = azurerm_user_assigned_identity.apply[each.key].principal_id
  principal_type       = "ServicePrincipal"
}

# ---------------------------------------------------------------------------
# Human read access to environment data (release evidence) for state admins.
# Granted here because the apply identity may not assign roles to users (ADR-0003).
# Read-only: evidence is written by the release identity and is immutable anyway.
# ---------------------------------------------------------------------------

resource "azurerm_role_assignment" "admin_env_blob_read" {
  for_each = { for pair in setproduct(tolist(local.envs), tolist(local.admin_ids)) :
  "${pair[0]}/${pair[1]}" => { env = pair[0], principal = pair[1] } }
  scope                = azurerm_resource_group.env[each.value.env].id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = each.value.principal
}
