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
