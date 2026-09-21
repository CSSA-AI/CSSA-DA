# Running the schema migrations against a database nothing outside the VPC can
# reach.
#
# Deliberately a task definition and not a service. A service exists to keep
# something running and replaces it when it stops; a migration that runs twice
# because ECS restarted it is the opposite of what anyone wants. This describes
# a container that does one thing and exits, and something has to ask for it to
# be run -- which is where the deployment gate goes.

resource "aws_cloudwatch_log_group" "migrate" {
  name = "/ecs/${local.name}-migrate"

  # Kept longer than the API's 30 days. There are only a handful of these
  # streams a year and each one answers "what changed in the database, and
  # when" -- a question that tends to be asked well after the fact.
  retention_in_days = 90

  tags = { Name = "/ecs/${local.name}-migrate" }
}

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${local.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  # Alembic loads no models and holds one connection. The API's 4GB is sized
  # for torch and two models; none of that runs here.
  cpu    = "256"
  memory = "512"

  # The image is built for Graviton. Without this the task definition defaults
  # to X86_64 and the container fails to start with an error about the image
  # manifest, which reads like a corrupt push rather than a wrong platform.
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  # The execution role is ECS's own identity: it pulls the image, writes to the
  # log group, and fetches the database secret before the container exists.
  execution_role_arn = aws_iam_role.ecs_task_execution.arn

  # No task role, deliberately. The API has one solely so `ecs exec` can open a
  # channel; this container calls no AWS API and should not be shelled into --
  # if a migration fails, the answer is in the log group, and the task is gone
  # by the time anyone looks. A role with nothing to do is a role that
  # eventually gets something added to it.

  container_definitions = jsonencode([
    {
      name      = "migrate"
      essential = true

      # The same image as the service, at the same tag. The tag is the commit,
      # so running this proves the migrations and the application code came
      # from one revision. A separate migration image would be a second thing
      # to build, and the first question after any incident would be which
      # version of it ran.
      image = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"

      # Overrides the image's uvicorn CMD. Everything Alembic needs to find its
      # way -- alembic.ini, migrations/, and the application package it now
      # imports the URL rule from -- is already in the image at /app.
      command = ["alembic", "upgrade", "head"]

      # No portMappings and no healthCheck: nothing connects to this, and the
      # only thing worth knowing about it is its exit code.

      # Only what a migration needs. The OpenAI and chat keys are not here
      # because Alembic has no use for them, and a credential that is never
      # injected cannot leak from a log or a crash dump.
      environment = [
        { name = "ENV", value = var.env },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "DB_HOST", value = aws_db_instance.main.address },
        { name = "DB_PORT", value = tostring(aws_db_instance.main.port) },
        { name = "DB_NAME", value = aws_db_instance.main.db_name },
      ]

      # migrations/env.py assembles DATABASE_URL from the parts above plus
      # these two, by the same rule the application uses
      # (app/core/database_url.py). That is why this command is a plain
      # `alembic upgrade head` rather than a shell wrapper that builds the URL
      # first -- the encoding rule has one home, and this is one of its callers.
      secrets = [
        {
          name      = "DB_USER"
          valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:username::"
        },
        {
          name      = "DB_PASSWORD"
          valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::"
        },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.migrate.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    },
  ])

  tags = { Name = "${local.name}-migrate" }
}
