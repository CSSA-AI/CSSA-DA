# What ECS itself is allowed to do on your behalf, before a container of yours
# is running: pull the image, open a log stream, and later read the database
# password out of Secrets Manager.
#
# This is the *execution* role. There is a second kind, the task role, which is
# what code inside the container would use to call AWS APIs -- the application
# calls OpenAI and Postgres, neither of which is an AWS API, so it needs none
# and none is defined here. Phase 3 adds one when the pipeline reads S3.

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "${local.name}-ecs-task-execution"

  # Who may wear this badge. Get this wrong and tasks fail to start with
  # "unable to assume role", while the permissions themselves are fine.
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = { Name = "${local.name}-ecs-task-execution" }
}

# AWS maintains this one and it is exactly the standard need: pull from ECR,
# write to CloudWatch Logs. Hand-writing the equivalent tends to miss something
# like ecr:GetAuthorizationToken, and the resulting failure does not name the
# missing permission.
#
# It does NOT grant reading Secrets Manager. Step 9 adds that separately, scoped
# to the one secret rather than to all of them.
resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
