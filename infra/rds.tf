# The knowledge base. Postgres with pgvector, matching the PostgreSQL 16 the
# project is developed against locally (docker-compose runs pgvector/pgvector
# on pg16), so the migrations and the VECTOR(384) column mean the same thing in
# both places.

# RDS insists on a subnet group spanning at least two availability zones even
# for a single-instance database. Both are private: nothing here has a route to
# the internet, and nothing on the internet has a route here.
resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${local.name}-db" }
}

resource "aws_db_instance" "main" {
  identifier = "${local.name}-db"

  engine         = "postgres"
  engine_version = "16.15"

  # Graviton, like the application image. Two burstable vCPUs and 1GB of memory
  # are ample for a few thousand rows scanned sequentially; resizing later is
  # one field and a few minutes of downtime.
  instance_class = "db.t4g.micro"

  # 20GB is the RDS minimum and far more than the corpus needs. The autoscaling
  # ceiling is not there for growth but for the dumbest possible outage: a full
  # disk takes the database down entirely.
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"

  # Free, no measurable overhead, and it cannot be turned on afterwards without
  # a snapshot-and-restore -- so it goes on now, before there is anything to
  # restore.
  storage_encrypted = true

  db_name  = "rag_vectordb"
  username = "cssa_admin"

  # AWS generates the password, stores it in Secrets Manager, and Terraform
  # never sees it. The alternative -- generating one here -- writes it into
  # state in the clear, where anyone who can read the state bucket can read the
  # database password. The cost is that a human connecting by hand has to fetch
  # it from Secrets Manager first.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  # A synchronous standby in the second zone doubles the bill to turn an outage
  # into a failover. An internal beta can be down for half an hour.
  multi_az = false

  # One day, not seven: this account is on the AWS Free Plan, which rejects a
  # longer retention outright (FreeTierRestrictionError). One day still means a
  # nightly snapshot and point-in-time recovery within that window -- thin, but
  # not nothing. Worth raising if the account ever moves to a paid plan.
  backup_retention_period = 1
  # 16:00 UTC is around 2am in Melbourne.
  backup_window      = "16:00-17:00"
  maintenance_window = "Sun:17:00-Sun:18:00"

  # Free for the first seven days of history, and the cheapest way to answer
  # "why was that request slow" once the service is actually serving.
  performance_insights_enabled = true

  # Changes take effect now rather than waiting for the maintenance window,
  # which is what you want while building this out.
  # TODO: reconsider once real traffic depends on it -- applying a resize
  # immediately at midday means downtime at midday.
  apply_immediately = true

  # TODO: both of these flip before real data lives here. Deletion protection
  # refuses `terraform destroy`, which is exactly the point once the corpus and
  # the interaction log are inside; a final snapshot is the last copy of a
  # database somebody deleted by accident.
  deletion_protection = false
  skip_final_snapshot = true

  tags = { Name = "${local.name}-db" }
}

# The execution role can now read the one secret RDS made, and nothing else in
# Secrets Manager. Scoping to this ARN rather than to the service is the whole
# point: the next secret that appears should require its own decision.
data "aws_iam_policy_document" "read_db_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_db_instance.main.master_user_secret[0].secret_arn]
  }
}

resource "aws_iam_role_policy" "ecs_read_db_secret" {
  name   = "${local.name}-read-db-secret"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.read_db_secret.json
}
