# The only way in from the internet. It sits in the public subnets, accepts
# connections there, and forwards them to tasks that have no public address of
# their own.

resource "aws_lb" "main" {
  name               = "${local.name}-alb"
  load_balancer_type = "application"
  internal           = false

  subnets         = aws_subnet.public[*].id
  security_groups = [aws_security_group.alb.id]

  # TODO: enable before this carries real traffic. Off for now so the stack can
  # still be destroyed and rebuilt while it is being assembled.
  enable_deletion_protection = false

  tags = { Name = "${local.name}-alb" }
}

resource "aws_lb_target_group" "api" {
  name     = "${local.name}-api"
  port     = 8000
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  # Fargate tasks are network interfaces, not machines, so targets are
  # registered by address rather than by instance.
  target_type = "ip"

  # Five minutes of draining by default. Requests here finish in seconds, and
  # the wait is otherwise added to every deployment.
  deregistration_delay = 30

  health_check {
    path     = "/health"
    protocol = "HTTP"
    matcher  = "200"

    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = { Name = "${local.name}-api" }
}

# HTTP only. The certificate 443 would need must be issued against a domain we
# own, and the load balancer's own hostname cannot carry one -- so until that
# domain exists this endpoint is for smoke tests. A browser will also refuse to
# call it from an HTTPS page, which is what makes the domain a prerequisite for
# the frontend rather than a nicety.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
