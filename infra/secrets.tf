# Two secrets the application needs that AWS does not generate for us. Only the
# containers are declared here -- the values are put in by hand afterwards, and
# never pass through Terraform.
#
# The reason is not that the state bucket is exposed; it is private and
# encrypted. It is that state is plaintext to anyone who can read it, that a
# teammate cannot be given "may run plan" without also being given "may read
# every secret", and that versioning keeps a rotated secret's old value forever.
# The database password already avoids all of this for free (RDS generates and
# holds it), so putting these two in state would mean running two different
# rules at once.
#
# To fill them, once:
#
#   printf 'sk-...' > /tmp/k
#   aws secretsmanager put-secret-value \
#     --secret-id cssa-da-prod-openai-api-key --secret-string file:///tmp/k
#   rm /tmp/k
#
# Via a file rather than an argument: an argument lands in shell history and is
# visible in the process list.

resource "aws_secretsmanager_secret" "openai_api_key" {
  name        = "${local.name}-openai-api-key"
  description = "OpenAI API key used by the chat generator."

  # Long enough to undo a mistaken delete, short enough not to block recreating
  # a secret of the same name during build-out.
  recovery_window_in_days = 7

  tags = { Name = "${local.name}-openai-api-key" }
}

resource "aws_secretsmanager_secret" "chat_api_key" {
  name        = "${local.name}-chat-api-key"
  description = "Shared key callers present to /v1/chat."

  recovery_window_in_days = 7

  tags = { Name = "${local.name}-chat-api-key" }
}

# Same scoping rule as the database secret: these ARNs, not Secrets Manager as
# a whole, so the next secret to appear needs its own decision.
data "aws_iam_policy_document" "read_app_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.openai_api_key.arn,
      aws_secretsmanager_secret.chat_api_key.arn,
    ]
  }
}

resource "aws_iam_role_policy" "ecs_read_app_secrets" {
  name   = "${local.name}-read-app-secrets"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.read_app_secrets.json
}
