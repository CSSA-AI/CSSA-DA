# Pinned so that every machine and every CI run resolves the same provider.
# An unpinned provider is how a plan that was clean yesterday proposes
# surprise changes today.
terraform {
  required_version = ">= 1.9"

  # State lives in S3 rather than on one laptop. Losing it would not lose the
  # infrastructure, but it would lose Terraform's knowledge of it: the next
  # apply would build a second copy of everything while the first kept running,
  # and billing, with nobody managing it.
  #
  # The bucket is deliberately NOT managed by this configuration -- state that
  # describes its own storage is a knot to untie during exactly the outage where
  # untying it is hardest. It was created by hand, alongside the budgets, as
  # account bootstrap.
  #
  # Values here cannot be variables: Terraform has to find the state before it
  # can read a variable file.
  backend "s3" {
    bucket = "cssa-da-tfstate-0cdc05d0"
    key    = "prod/terraform.tfstate"
    region = "ap-southeast-2"

    # S3 holds the lock itself since Terraform 1.10, so two applies cannot
    # interleave and corrupt the state. This used to require a DynamoDB table.
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
