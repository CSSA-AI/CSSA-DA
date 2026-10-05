# The service itself: a cluster to put it in, a description of what to run, and
# something that keeps one of them running.
#
# No load balancer yet -- that arrives with the ALB, and until then the task is
# reachable only from inside the VPC. That is enough to see whether it starts,
# loads its models, and finds the database.

resource "aws_ecs_cluster" "main" {
  name = "${local.name}-cluster"

  tags = { Name = "${local.name}-cluster" }
}

# --- task role --------------------------------------------------------------
# Distinct from the execution role: this one belongs to the running container
# rather than to ECS. The application still calls no AWS API -- OpenAI and
# Postgres are neither -- so the only reason this exists is `ecs exec`, whose
# agent inside the container opens a channel back to AWS. Migrations and the
# first corpus import run through that channel instead of through a bastion.
#
# If exec is ever turned off, this role has no other purpose and should go.

data "aws_iam_policy_document" "ecs_exec" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    # Channel actions are not addressed to a resource, so there is nothing
    # narrower to name here.
    resources = ["*"]
  }
}

resource "aws_iam_role" "ecs_task" {
  name               = "${local.name}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = { Name = "${local.name}-ecs-task" }
}

resource "aws_iam_role_policy" "ecs_exec" {
  name   = "${local.name}-ecs-exec"
  role   = aws_iam_role.ecs_task.id
  policy = data.aws_iam_policy_document.ecs_exec.json
}

# --- what to run ------------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  # Deliberately generous for a first boot. The only memory figure on record
  # (944MiB idle) was measured on x86 and before warm-up, so it is a guess
  # here. Debugging an out-of-memory kill costs more than a few days of the
  # next tier down; measure once it is running, then trim.
  cpu    = "1024"
  memory = "4096"

  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }

  execution_role_arn = aws_iam_role.ecs_task_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        },
      ]

      # Everything that is not a credential. DB_HOST/PORT/NAME are the parts
      # the application assembles DATABASE_URL from, because a secret field can
      # be injected but two of them cannot be concatenated.
      environment = [
        { name = "ENV", value = var.env },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "DB_HOST", value = aws_db_instance.main.address },
        { name = "DB_PORT", value = tostring(aws_db_instance.main.port) },
        { name = "DB_NAME", value = aws_db_instance.main.db_name },
        # One of the four version coordinates on every chat_interactions row,
        # and true by construction: the tag is the commit.
        { name = "GIT_SHA", value = var.image_tag },
      ]

      # Fetched by ECS at start-up and injected as environment variables. The
      # container never holds a credential to read them with -- the execution
      # role does that before the container exists.
      #
      # The ":field::" suffix picks one key out of the JSON document RDS keeps.
      secrets = [
        {
          name      = "OPENAI_API_KEY"
          valueFrom = aws_secretsmanager_secret.openai_api_key.arn
        },
        {
          name      = "CHAT_API_KEY"
          valueFrom = aws_secretsmanager_secret.chat_api_key.arn
        },
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
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }

      # /health, not /ready: this decides whether the container is alive, and
      # an empty database is not a dead container. The start period is long
      # because start-up loads two models and runs one inference through each
      # before answering -- cut it too fine and ECS kills a container that was
      # merely still starting.
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)\" || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 120
      }
    },
  ])

  tags = { Name = "${local.name}-api" }
}

# --- keep one running -------------------------------------------------------

resource "aws_ecs_service" "api" {
  name            = "${local.name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  launch_type     = "FARGATE"

  # One task. A second would buy availability during a deploy or a zone
  # failure, at twice the compute bill, which an internal beta does not need.
  desired_count = 1

  # Lets `aws ecs execute-command` open a shell in the running container, which
  # is how migrations and the first corpus import reach a database that has no
  # public address.
  enable_execute_command = true

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  # Cold start measured at 57 seconds: pulling the image, then loading two
  # models and running one inference through each. Without this window the load
  # balancer calls a starting container unhealthy, ECS replaces it, and the
  # replacement is killed at the same point -- a crash loop whose logs say
  # nothing about the container merely being slow to start.
  health_check_grace_period_seconds = 180

  # A deployment that never reaches a healthy state is rolled back instead of
  # being retried forever. Without this a bad image quietly replaces a working
  # one and the service sits down.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # The role exists as soon as it is created, but the policies granting it the
  # secrets are separate resources. Without this the first task can start
  # before they attach and fail to fetch its credentials -- an error that
  # disappears on the next attempt and therefore reads as a fluke.
  depends_on = [
    aws_iam_role_policy.ecs_read_db_secret,
    aws_iam_role_policy.ecs_read_app_secrets,
    aws_iam_role_policy.ecs_exec,
  ]

  tags = { Name = "${local.name}-api" }
}
