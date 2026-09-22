# Which database identity each task gets, and whether the corpus coordinate
# reaches the API (#105). Runs against a mocked AWS provider -- no account, no
# credentials, nothing created:
#
#   terraform -chdir=infra init -backend=false
#   terraform -chdir=infra test
#
# Not run in CI yet (CI has no Terraform step); run it after changing
# ecs.tf, ecs_migrate.tf, secrets.tf or variables.tf.

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-southeast-2a", "ap-southeast-2b", "ap-southeast-2c"] }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_resource "aws_db_instance" {
    defaults = {
      address            = "db.example.internal"
      port               = 5432
      master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:master", kms_key_id = "k", secret_status = "active" }]
    }
  }
  # The provider validates ARNs, so the mocks need real-looking ones.
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-southeast-2:123456789012:loadbalancer/app/mock/1", dns_name = "mock.example" }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-southeast-2:123456789012:targetgroup/mock/1" }
  }
  mock_resource "aws_ecs_cluster" {
    defaults = { arn = "arn:aws:ecs:ap-southeast-2:123456789012:cluster/mock" }
  }
  mock_resource "aws_ecs_task_definition" {
    defaults = { arn = "arn:aws:ecs:ap-southeast-2:123456789012:task-definition/mock:1" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:app" }
  }
}

# A distinct ARN, so the tests can tell the runtime password from the others.
override_resource {
  target = aws_secretsmanager_secret.runtime_db_password
  values = { arn = "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:runtime" }
}

run "api_runs_as_the_runtime_role" {
  command = apply

  assert {
    condition     = one([for e in jsondecode(aws_ecs_task_definition.api.container_definitions)[0].environment : e.value if e.name == "DB_USER"]) == "cssa_app"
    error_message = "The API must connect as cssa_app."
  }
  assert {
    condition     = one([for s in jsondecode(aws_ecs_task_definition.api.container_definitions)[0].secrets : s.valueFrom if s.name == "DB_PASSWORD"]) == "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:runtime"
    error_message = "The API's DB_PASSWORD must come from the runtime password secret."
  }
  assert {
    condition     = alltrue([for s in jsondecode(aws_ecs_task_definition.api.container_definitions)[0].secrets : !strcontains(s.valueFrom, "secret:master")])
    error_message = "The API must not be given the RDS master secret."
  }
  assert {
    condition     = !contains([for e in jsondecode(aws_ecs_task_definition.api.container_definitions)[0].environment : e.name], "CORPUS_SHA256")
    error_message = "CORPUS_SHA256 must be left out while the variable is null, so the fingerprint records null, not an empty string."
  }
}

run "migrate_keeps_the_master_and_provisions_the_role" {
  command = apply

  assert {
    condition     = jsondecode(aws_ecs_task_definition.migrate.container_definitions)[0].command == ["sh", "-c", "alembic upgrade head && python -m ops.provision_runtime_role"]
    error_message = "The migrate task must provision the runtime role after migrating."
  }
  assert {
    condition     = strcontains(one([for s in jsondecode(aws_ecs_task_definition.migrate.container_definitions)[0].secrets : s.valueFrom if s.name == "DB_USER"]), "secret:master")
    error_message = "The migrate task must still run as the RDS master user."
  }
  assert {
    condition     = one([for s in jsondecode(aws_ecs_task_definition.migrate.container_definitions)[0].secrets : s.valueFrom if s.name == "RUNTIME_DB_PASSWORD"]) == "arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:runtime"
    error_message = "The migrate task sets the runtime role's password from the same secret the API reads."
  }
  assert {
    condition     = one([for e in jsondecode(aws_ecs_task_definition.migrate.container_definitions)[0].environment : e.value if e.name == "RUNTIME_DB_USER"]) == "cssa_app"
    error_message = "The migrate task must provision the role the API connects as."
  }
}

run "corpus_sha256_reaches_the_api" {
  command = apply

  variables {
    corpus_sha256 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  }

  assert {
    condition     = one([for e in jsondecode(aws_ecs_task_definition.api.container_definitions)[0].environment : e.value if e.name == "CORPUS_SHA256"]) == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    error_message = "A recorded corpus_sha256 must reach the API task as CORPUS_SHA256."
  }
}

run "a_malformed_corpus_sha256_is_rejected" {
  command = plan

  variables {
    corpus_sha256 = "not-a-hash"
  }

  expect_failures = [var.corpus_sha256]
}
