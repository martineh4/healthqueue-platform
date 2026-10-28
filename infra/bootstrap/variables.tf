# Inputs. Defaults describe this repository's environment; nothing secret has a default.

variable "location" {
  description = "Azure region for all bootstrap resources. See docs/adr/0001-azure-region-selection.md."
  type        = string
  default     = "swedencentral"
}

variable "environments" {
  description = <<-EOT
    Environments to provision. Each gets its own resource group, state container, state
    encryption key, and a pair of GitHub Actions identities (plan and apply).
  EOT
  type        = set(string)
  default     = ["prod"]
}

variable "state_admin_object_ids" {
  description = <<-EOT
    Additional Entra object IDs (users or groups) that administer state: read/write state
    blobs and manage encryption keys. The identity running `tofu apply` is always included.
  EOT
  type        = list(string)
  default     = []
}

variable "github_oidc_subject_prefix" {
  description = <<-EOT
    Prefix of the `sub` claim in this repository's GitHub Actions OIDC tokens. The repository
    uses immutable subjects (owner and repository IDs, not just names), so a deleted and
    re-created repository with the same name cannot assume these identities. Read it with:
    gh api repos/OWNER/REPO/actions/oidc/customization/sub --jq .sub_claim_prefix
  EOT
  type        = string
  default     = "repo:martineh4@230047607/healthqueue-platform@1432743551"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    project             = "healthqueue"
    component           = "tfstate"
    managed_by          = "opentofu"
    repository          = "martineh4/healthqueue-platform"
    data_classification = "internal-no-phi"
  }
}

variable "subscription_id" {
  description = "Azure subscription ID. Pass via TF_VAR_subscription_id; never commit it."
  type        = string
  sensitive   = true
}
