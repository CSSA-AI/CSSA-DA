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
