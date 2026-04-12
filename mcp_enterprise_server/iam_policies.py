"""
IAM Policy Templates for MCP Enterprise Server
================================================
These are the minimum-privilege IAM policies required for each MCP tool set.

IMPORTANT: Apply these to the IAM roles referenced in the config
(DYNAMODB_ROLE_ARN, ATHENA_ROLE_ARN). Never use admin credentials.

These are Python dicts matching the AWS IAM Policy JSON schema.
Export them via `json.dumps()` and apply via CloudFormation, CDK, or console.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# DynamoDB — Read-Only Policy
# ---------------------------------------------------------------------------
DYNAMODB_READ_ONLY_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "MCPDynamoDBReadOnly",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:BatchGetItem",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:DescribeTable",
                "dynamodb:ListTables",
            ],
            "Resource": ["arn:aws:dynamodb:*:ACCOUNT_ID:table/*"],
            "Condition": {"StringEquals": {"aws:RequestedRegion": ["us-east-1", "us-west-2"]}},
        },
    ],
}


# ---------------------------------------------------------------------------
# DynamoDB — Read-Write Policy (for teams needing write access)
# ---------------------------------------------------------------------------
DYNAMODB_READ_WRITE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "MCPDynamoDBReadWrite",
            "Effect": "Allow",
            "Action": [
                "dynamodb:GetItem",
                "dynamodb:BatchGetItem",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:DescribeTable",
                "dynamodb:ListTables",
                "dynamodb:PutItem",
                "dynamodb:UpdateItem",
                "dynamodb:BatchWriteItem",
            ],
            "Resource": [
                "arn:aws:dynamodb:*:ACCOUNT_ID:table/ALLOWED_TABLE_1",
                "arn:aws:dynamodb:*:ACCOUNT_ID:table/ALLOWED_TABLE_2",
            ],
        },
        {
            "Sid": "DenyDangerousOps",
            "Effect": "Deny",
            "Action": [
                "dynamodb:DeleteTable",
                "dynamodb:CreateTable",
                "dynamodb:DeleteItem",
                "dynamodb:UpdateTable",
            ],
            "Resource": "*",
        },
    ],
}


# ---------------------------------------------------------------------------
# Athena — Read-Only Query Policy
# ---------------------------------------------------------------------------
ATHENA_READ_ONLY_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "MCPAthenaQuery",
            "Effect": "Allow",
            "Action": [
                "athena:StartQueryExecution",
                "athena:StopQueryExecution",
                "athena:GetQueryExecution",
                "athena:GetQueryResults",
                "athena:ListDatabases",
                "athena:ListTableMetadata",
                "athena:GetTableMetadata",
                "athena:ListQueryExecutions",
            ],
            "Resource": ["arn:aws:athena:*:ACCOUNT_ID:workgroup/primary"],
        },
        {
            "Sid": "MCPAthenaS3Results",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:ListBucket",
                "s3:GetBucketLocation",
            ],
            "Resource": [
                "arn:aws:s3:::enterprise-mcp-athena-results",
                "arn:aws:s3:::enterprise-mcp-athena-results/*",
            ],
        },
        {
            "Sid": "MCPGlueCatalog",
            "Effect": "Allow",
            "Action": [
                "glue:GetDatabase",
                "glue:GetDatabases",
                "glue:GetTable",
                "glue:GetTables",
                "glue:GetPartitions",
            ],
            "Resource": [
                "arn:aws:glue:*:ACCOUNT_ID:catalog",
                "arn:aws:glue:*:ACCOUNT_ID:database/*",
                "arn:aws:glue:*:ACCOUNT_ID:table/*/*",
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# STS AssumeRole Trust Policy (for MCP server)
# ---------------------------------------------------------------------------
MCP_SERVER_TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowMCPServerAssumeRole",
            "Effect": "Allow",
            "Principal": {"AWS": "arn:aws:iam::ACCOUNT_ID:role/MCP-Server-EC2-Role"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"sts:ExternalId": "mcp-enterprise-server"}},
        }
    ],
}


# ---------------------------------------------------------------------------
# S3 — Read-Only Policy
# ---------------------------------------------------------------------------
S3_READ_ONLY_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "MCPS3ReadOnly",
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:GetObjectVersion",
                "s3:HeadObject",
                "s3:ListBucket",
                "s3:ListBucketVersions",
                "s3:GetBucketLocation",
            ],
            "Resource": [
                "arn:aws:s3:::ALLOWED_BUCKET_1",
                "arn:aws:s3:::ALLOWED_BUCKET_1/*",
                "arn:aws:s3:::ALLOWED_BUCKET_2",
                "arn:aws:s3:::ALLOWED_BUCKET_2/*",
            ],
            "Condition": {"StringEquals": {"aws:RequestedRegion": ["us-east-1", "us-west-2"]}},
        },
        {
            "Sid": "MCPS3ListAllBuckets",
            "Effect": "Allow",
            "Action": [
                "s3:ListAllMyBuckets",
            ],
            "Resource": "*",
        },
        {
            "Sid": "DenyS3Write",
            "Effect": "Deny",
            "Action": [
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:DeleteBucket",
                "s3:PutBucketPolicy",
            ],
            "Resource": "*",
        },
    ],
}


# ---------------------------------------------------------------------------
# Helper: Export policies as JSON files
# ---------------------------------------------------------------------------
def export_policies(output_dir: str = ".") -> None:
    """Export all IAM policies as JSON files for CloudFormation/CDK use."""
    import os

    os.makedirs(output_dir, exist_ok=True)

    policies = {
        "dynamodb_read_only_policy.json": DYNAMODB_READ_ONLY_POLICY,
        "dynamodb_read_write_policy.json": DYNAMODB_READ_WRITE_POLICY,
        "athena_read_only_policy.json": ATHENA_READ_ONLY_POLICY,
        "s3_read_only_policy.json": S3_READ_ONLY_POLICY,
        "mcp_server_trust_policy.json": MCP_SERVER_TRUST_POLICY,
    }

    for filename, policy in policies.items():
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w") as f:
            json.dump(policy, f, indent=2)
        print(f"Exported: {filepath}")


if __name__ == "__main__":
    export_policies("./iam_policies")
