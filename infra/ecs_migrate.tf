# Running the schema migrations against a database nothing outside the VPC can
# reach -- and, as the same identity, everything else that must not be done by
# the API's own database role: keeping that role's privileges exact after each
# migration, and loading the corpus (a one-off run of this task definition with
# the command overridden, see docs/deployment.md).
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
  # for torch and two models; none of that runs here. A corpus import run from
  # this definition does load the embedding model, so that run overrides cpu
  # and memory (docs/deployment.md).
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
      #
      # Then the runtime role: created on the first run, afterwards re-granted
      # exactly its privilege list and checked, so a new table's grant lands
      # with the migration that created it. `&&` so a failed migration never
      # reaches it, and the task's exit code is whichever step failed. It needs
      # a shell for that -- no URL is built here; both steps assemble it from
      # the DB_* parts through app/core/database_url.py.
      command = [
        "sh", "-c",
        "alembic upgrade head && python -m ops.provision_runtime_role",
      ]

      # No portMappings and no healthCheck: nothing connects to this, and the
      # only thing worth knowing about it is its exit code.

      # Only what the migration and the role provisioning need. The OpenAI and
      # chat keys are not here because neither has any use for them, and a
      # credential that is never injected cannot leak from a log or a crash
      # dump.
      environment = [
        { name = "ENV", value = var.env },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "DB_HOST", value = aws_db_instance.main.address },
        { name = "DB_PORT", value = tostring(aws_db_instance.main.port) },
        { name = "DB_NAME", value = aws_db_instance.main.db_name },
        { name = "RUNTIME_DB_USER", value = var.runtime_db_user },
      ]

      # migrations/env.py assembles DATABASE_URL from the parts above plus
      # these two, by the same rule the application uses
      # (app/core/database_url.py), and so do provision_runtime_role and the
      # pipelines CLI through Settings. That is why the command never builds a
      # URL itself -- the encoding rule has one home, and these are its callers.
      secrets = [
        {
          name      = "DB_USER"
          valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:username::"
        },
        {
          name      = "DB_PASSWORD"
          valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::"
        },
        # What provision_runtime_role sets the runtime role's password to --
        # the same secret the API task logs in with.
        {
          name      = "RUNTIME_DB_PASSWORD"
          valueFrom = aws_secretsmanager_secret.runtime_db_password.arn
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

  # The execution role's permission to read the secrets above is a separate
  # resource. Depending on it means a targeted
  # `terraform apply -target=aws_ecs_task_definition.migrate`
  # (docs/deployment.md) brings the permission along, instead of registering a
  # task whose new secret the role cannot read yet -- which stops with exitCode
  # null and reads like a broken image.
  depends_on = [
    aws_iam_role_policy.ecs_read_db_secret,
    aws_iam_role_policy.ecs_read_app_secrets,
  ]

  tags = { Name = "${local.name}-migrate" }
}
