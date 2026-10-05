variable "project" {
  description = "Project slug, used as the prefix of every resource name."
  type        = string
  default     = "cssa-da"
}

variable "env" {
  description = "Environment segment of resource names. v1 only has prod."
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "Sydney: the users are in Melbourne."
  type        = string
  default     = "ap-southeast-2"
}

variable "vpc_cidr" {
  description = "Address range of the VPC. /16 is far more than this project needs, and costs nothing."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Both the ALB and the RDS subnet group require at least two availability zones."
  type        = number
  default     = 2
}

variable "image_tag" {
  description = "Image to run, which is the Git SHA it was built from. Bumping this and applying is a deploy."
  type        = string
  default     = "42d00a10"
}
