terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket = "dead-gecco-prod-tfstate"
    key    = "tfstate"
    region = "us-east-2"
  }
}

locals {
  env = "prod"
}

provider "aws" {
  region = "us-east-2"
  default_tags {
    tags = {
      env = local.env
    }
  }
}

resource "aws_s3_bucket" "features_raw" {
  bucket = "dead-gecco-${local.env}-features-raw"
}

resource "aws_s3_bucket_versioning" "features_raw" {
  bucket = aws_s3_bucket.features_raw.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "features_raw" {
  bucket = aws_s3_bucket.features_raw.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_policy" "features_raw_source_rw" {
  for_each = toset([ "cole", "test", "databento" ])
  name        = "features_raw_${local.env}_${each.key}_rw"
  path        = "/"
  description = "Read and write to the raw ${local.env} ${each.key} features."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:DeleteObject",
        ]
        Effect   = "Allow"
        Resource = "${aws_s3_bucket.features_raw.arn}/${each.key}/*"
      },
    ]
  })
}

resource "aws_iam_policy" "features_raw_all_rw" {
  name        = "features_raw_${local.env}_all_rw"
  path        = "/"
  description = "Read and write to the ${local.env} raw features."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:DeleteObject",
        ]
        Effect   = "Allow"
        Resource = "${aws_s3_bucket.features_raw.arn}/*"
      },
    ]
  })
}
