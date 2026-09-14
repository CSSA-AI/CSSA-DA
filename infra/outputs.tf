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
