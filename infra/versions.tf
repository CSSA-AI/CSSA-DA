# Pinned so that every machine and every CI run resolves the same provider.
# An unpinned provider is how a plan that was clean yesterday proposes
# surprise changes today.
terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
