# Inputs. The subscription ID is never committed: CI passes it from a GitHub secret.

variable "location" {
  description = "Azure region. See docs/adr/0001-azure-region-selection.md."
  type        = string
  default     = "swedencentral"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    project             = "healthqueue"
    environment         = "prod"
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

variable "github_oidc_subject_prefix" {
  description = "Prefix of this repository's immutable GitHub OIDC `sub` claim. See bootstrap/variables.tf."
  type        = string
  default     = "repo:martineh4@230047607/healthqueue-platform@1432743551"
}

variable "evidence_retention_days" {
  description = "WORM retention for release evidence. Short for the course; 2190 (six years) in production."
  type        = number
  default     = 7
}
