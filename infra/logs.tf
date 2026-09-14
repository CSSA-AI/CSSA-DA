# Where the container's stdout goes. ECS would create this on its own if it were
# missing, but that one is not managed here and keeps logs forever -- storage
# that grows without end and that nobody decided on.
resource "aws_cloudwatch_log_group" "api" {
  name = "/ecs/${local.name}-api"

  # Long enough to investigate "what happened last week", short enough that
  # nothing accumulates unnoticed.
  retention_in_days = 30

  tags = { Name = "/ecs/${local.name}-api" }
}
