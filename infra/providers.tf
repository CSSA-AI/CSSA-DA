provider "aws" {
  region = var.aws_region

  # Applied to every taggable resource this provider creates, so tagging can
  # never drift from being done by hand. ManagedBy answers the question that
  # matters six months from now: is this resource deleted here, or in the
  # console?
  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
    }
  }
}
