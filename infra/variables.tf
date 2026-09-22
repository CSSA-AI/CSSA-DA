variable "project" {
  description = "Project slug, used as the prefix of every resource name."
  type        = string
  default     = "cssa-da"
}

variable "env" {
  description = "Environment segment of resource names. v1 only has prod."
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "Sydney: the users are in Melbourne."
  type        = string
  default     = "ap-southeast-2"
}

variable "vpc_cidr" {
  description = "Address range of the VPC. /16 is far more than this project needs, and costs nothing."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Both the ALB and the RDS subnet group require at least two availability zones."
  type        = number
  default     = 2
}

variable "image_tag" {
  description = "Image to run, which is the Git SHA it was built from. Bumping this and applying is a deploy."
  type        = string
  default     = "42d00a10"
}

variable "runtime_db_user" {
  description = "Database role the API connects as. Created and kept least-privilege by ops/provision_runtime_role.py, which the migrate task runs; never the RDS master user."
  type        = string
  default     = "cssa_app"
}

# Which corpus the database holds: the corpus_sha256 printed by the import that
# loaded it, stamped onto every chat_interactions row. A default here rather
# than a -var on the command line, for two reasons. A -var forgotten once drops
# the variable from the next task definition and every row goes back to null
# without anyone noticing; and a value committed here means "when did the
# corpus change, and to what" is answered by git history.
#
# null until the first import that records it has run (docs/deployment.md,
# "Loading or refreshing the corpus"). Never compute it from a file afterwards:
# the value only means something because it came from the run that loaded the
# data.
variable "corpus_sha256" {
  description = "corpus_sha256 from the import that loaded the production corpus, or null."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.corpus_sha256 == null || can(regex("^[0-9a-f]{64}$", var.corpus_sha256))
    error_message = "corpus_sha256 must be the 64-character lowercase hex value the import printed."
  }
}
