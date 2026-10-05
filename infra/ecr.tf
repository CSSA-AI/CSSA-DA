# Where the API image lives. Fargate cannot pull from a laptop, so every deploy
# starts with a push to here.
#
# The pipeline image (Dockerfile.pipeline) is a separate artifact with its own
# dependency group, and gets its own repository when Phase 3 moves the pipeline
# to AWS. Not here yet.

resource "aws_ecr_repository" "api" {
  # No environment segment: the image is one artifact. If a staging environment
  # ever exists it runs this same image with different configuration.
  name = "${var.project}-api"

  # A tag can never be overwritten. This is what makes "which code is running?"
  # answerable: the tag is the Git SHA, and that tag will always be the same
  # bytes. The cost is that rebuilding the same commit needs the old image
  # deleted first, which is rare enough to be worth it.
  image_tag_mutability = "IMMUTABLE"

  # Free, and only runs at push time -- it will not notice a CVE published
  # after the image was pushed. Treat it as a smoke alarm, not a security
  # programme.
  image_scanning_configuration {
    scan_on_push = true
  }

  # ECR refuses to delete a repository that still holds images, which would
  # make `terraform destroy` fail during the build-out.
  # TODO: set to false once this stack is serving real traffic -- by then an
  # accidental destroy wiping the image history is the bigger risk.
  force_delete = true

  tags = { Name = "${var.project}-api" }
}

# Layers are shared between images, so an extra image mostly costs only the
# layers that changed -- the multi-GB torch and model layers are pushed once and
# reused. The limit is therefore about how far back a rollback can reach, not
# about storage: five is a couple of rollbacks plus a little history.
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after a day: build leftovers, not releases."
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        # A tagStatus of "any" has to be the last rule ECR evaluates.
        rulePriority = 2
        description  = "Keep the five most recent images."
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = { type = "expire" }
      },
    ]
  })
}
