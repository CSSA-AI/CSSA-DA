# The network the whole system sits in. Everything here is free: a VPC,
# subnets, route tables, an internet gateway and a gateway endpoint carry no
# charge. The first resource that costs money is the NAT gateway, which is
# deliberately not here yet -- see the note at the bottom of this file.

locals {
  name = "${var.project}-${var.env}"

  # Queried rather than hard-coded: AWS maps zone names onto different physical
  # data centres per account, and not every account is offered every zone.
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr

  # Both are required for the container to resolve the hostname RDS hands out.
  # Without them a database connection fails as a timeout, which reads like a
  # security group problem and sends you looking in the wrong place.
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.name}-vpc" }
}

# --- public side ------------------------------------------------------------
# A subnet is not "public" by nature. It is public because its route table
# sends 0.0.0.0/0 to an internet gateway. That single line below is the whole
# difference between the two kinds of subnet in this file.

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-igw" }
}

# Each subnet is a /20 carved out of the /16. Public subnets take the low end of
# the range and private ones the high end (the + 8 further down), so an address
# on its own says which side it is on: 10.0.16.x is public, 10.0.144.x is not.
resource "aws_subnet" "public" {
  count = var.az_count

  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index)

  tags = { Name = "${local.name}-public-${substr(local.azs[count.index], -1, 1)}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  count = var.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --- private side -----------------------------------------------------------
# No 0.0.0.0/0 route, so nothing in here can reach the internet at all yet.
# The API and the database live here.

resource "aws_subnet" "private" {
  count = var.az_count

  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + 8)

  tags = { Name = "${local.name}-private-${substr(local.azs[count.index], -1, 1)}" }
}

# One route table per availability zone rather than one shared table: a NAT
# gateway is per-AZ, so when one is added each zone needs its own default
# route. Sharing a table now would have to be undone then.
resource "aws_route_table" "private" {
  count = var.az_count

  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-private-${substr(local.azs[count.index], -1, 1)}" }
}

resource "aws_route_table_association" "private" {
  count = var.az_count

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# --- S3 gateway endpoint ----------------------------------------------------
# Free, because a gateway endpoint is a route table entry rather than a running
# appliance. It earns its place immediately: ECR stores image layers in S3, and
# the API image is several GB, so without this every task launch drags the
# whole image through the NAT gateway and pays per GB for it.

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id

  tags = { Name = "${local.name}-s3" }
}

# --- not here yet -----------------------------------------------------------
# NAT gateway: needed before the API can call OpenAI, and the first thing in
# this stack that bills by the hour. Added when ECS is, not before.
