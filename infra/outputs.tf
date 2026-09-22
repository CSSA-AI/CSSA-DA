# Consumed by later stacks (ECS, RDS, ALB) and handy for eyeballing what was
# built without opening the console.

output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "availability_zones" {
  value = local.azs
}

# The address `docker push` needs, and what the ECS task definition points at.
output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

# Host half of DATABASE_URL. The credentials come from Secrets Manager, not
# from here.
output "db_endpoint" {
  value = aws_db_instance.main.endpoint
}

output "db_secret_arn" {
  value = aws_db_instance.main.master_user_secret[0].secret_arn
}

# Needed to open a shell in the running container:
#   aws ecs execute-command --cluster <cluster> --task <id> \
#     --container api --interactive --command /bin/sh
output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.api.name
}

# The address the service answers on, until a real domain points at it.
output "alb_url" {
  value = "http://${aws_lb.main.dns_name}"
}

# Where pipeline inputs are staged. `aws s3 cp` targets this, and the presigned
# URL the container fetches with is generated against it.
output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

# Under awsvpc the network is chosen when a task is RUN, not when it is
# defined, so anything launching the migration task has to supply these
# alongside the family below. `private_subnet_ids` above is the other half.
output "ecs_tasks_security_group_id" {
  value = aws_security_group.ecs_tasks.id
}

# For checking that nothing was ever opened to the database (#105): list this
# group's rules live, since a rule added by hand in the console would appear
# neither in security_groups.tf nor as drift in `terraform plan`.
#   aws ec2 describe-security-group-rules \
#     --filters Name=group-id,Values=$(terraform -chdir=infra output -raw rds_security_group_id)
output "rds_security_group_id" {
  value = aws_security_group.rds.id
}

# The role the API connects as, and where its password lives.
output "runtime_db_user" {
  value = var.runtime_db_user
}

output "runtime_db_password_secret_name" {
  value = aws_secretsmanager_secret.runtime_db_password.name
}

output "ecs_migrate_task_family" {
  value = aws_ecs_task_definition.migrate.family
}
