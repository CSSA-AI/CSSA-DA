# One security group per tier, each opened only to the tier in front of it:
#
#   internet --> ALB --> ECS task --> RDS
#
# The rules reference each other by security group rather than by address
# range, so they keep holding as containers are replaced and get new addresses.
# Nothing in here has to change when the service scales.
#
# Note on egress: AWS adds an allow-all outbound rule to a new security group,
# and Terraform removes it. Whatever a tier needs on the way out has to be
# stated, or the connection fails as a timeout with no rule to point at.

# --- ALB: the only thing the internet can reach -----------------------------

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public entry point. Terminates client connections."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-alb" }
}

# Port 80 only, because the certificate needed for 443 has to be issued against
# a domain we own, and the ALB's own hostname cannot carry one. 443 arrives
# together with the domain; until then this endpoint is for smoke tests, not
# for real traffic -- the API key would cross the network in the clear.
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from anywhere"

  cidr_ipv4   = "0.0.0.0/0"
  from_port   = 80
  to_port     = 80
  ip_protocol = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_tasks" {
  security_group_id = aws_security_group.alb.id
  description       = "Forward to the application containers"

  referenced_security_group_id = aws_security_group.ecs_tasks.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

# --- ECS tasks: reachable only from the load balancer -----------------------

resource "aws_security_group" "ecs_tasks" {
  name        = "${local.name}-ecs-tasks"
  description = "Application containers. Private subnets only."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-ecs-tasks" }
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id = aws_security_group.ecs_tasks.id
  description       = "Only the load balancer, on the port uvicorn listens on"

  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

# Outbound stays wide: the container calls OpenAI, pulls image layers from S3
# through the gateway endpoint, reaches Postgres, and resolves DNS. Narrowing
# this would mean enumerating OpenAI's addresses, which change without notice --
# a rule that breaks silently in production is worse than a broad one here.
# Inbound is where this tier is actually protected.
resource "aws_vpc_security_group_egress_rule" "tasks_outbound" {
  security_group_id = aws_security_group.ecs_tasks.id
  description       = "Outbound to anywhere"

  cidr_ipv4   = "0.0.0.0/0"
  ip_protocol = "-1"
}

# --- RDS: reachable only from the tasks -------------------------------------

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds"
  description = "Postgres. No route to or from the internet."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-rds" }
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_tasks" {
  security_group_id = aws_security_group.rds.id
  description       = "Postgres, from the application containers only"

  referenced_security_group_id = aws_security_group.ecs_tasks.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

# No egress rule: the database answers connections, it never opens any. Leaving
# it with nothing on the way out is deliberate, not an omission.
