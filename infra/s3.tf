# Pipeline data. The corpus, its intermediate forms, and anything else that is
# a file rather than a row.
#
# The split against RDS is the one that matters: Postgres holds `knowledge_base`
# because those rows get queried -- filtered, ranked, joined to a vector index.
# The 12MB of JSON they were built from is never queried, only read once and
# transformed, so paying database prices to store it would buy nothing.
#
# The immediate reason this exists is more mundane: RDS is in the private
# subnets, so a laptop cannot reach it, and the container that CAN reach it has
# no copy of the corpus (data/* is excluded from the image). This bucket is the
# one place both ends can see.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "data" {
  # Bucket names are global across every AWS account, so the project slug alone
  # would collide with anyone else who picked it. The account ID is the cheapest
  # unique suffix that is also stable -- a `random_id` would pull in another
  # provider, and re-rolling it would silently orphan the old bucket.
  bucket = "${local.name}-data-${data.aws_caller_identity.current.account_id}"

  # TODO: remove before real data lives here. Versioning means a non-empty
  # bucket, and S3 refuses to delete one -- which would make `terraform destroy`
  # fail during build-out, exactly when tearing the stack down nightly is the
  # point. Once the corpus is not trivially re-importable, that refusal is the
  # feature.
  force_destroy = true

  tags = { Name = "${local.name}-data" }
}

# Nothing here is public. This is four separate settings rather than one because
# S3's default was once "public unless told otherwise", and the account-level
# accidents that caused are why the block exists at all.
resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3, not KMS. KMS would add a per-request charge and a key to manage, and
# buys something this bucket does not need: the ability to revoke access to the
# data by revoking the key. The corpus is public WeChat articles.
resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# `current/` is a stable key that gets overwritten in place, so without
# versioning a bad transform silently destroys the good input it replaced.
# Versioning makes that recoverable; the lifecycle rule below is what stops it
# from also making the bucket grow forever.
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  # Both rules only ever delete things that are already invisible: superseded
  # versions and uploads that never finished. Nothing here expires an object a
  # pipeline would still read, because "temporary" describes how the data got
  # here, not how long it should survive -- deciding that per prefix is a
  # separate decision, made when there is something to decide about.
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"

    filter {}

    # A multipart upload interrupted halfway leaves parts that are billed but
    # belong to no object, and are invisible in the console's object list.
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.data]
}
