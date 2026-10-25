variable "location" {
  description = "Azure region for all bootstrap resources. See docs/adr/0001-azure-region-selection.md."
  type        = string
  default     = "swedencentral"
}

variable "environments" {
  description = "Environments that get their own state encryption key (one key per state file)."
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
