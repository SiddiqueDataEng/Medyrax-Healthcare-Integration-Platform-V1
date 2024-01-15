"""
Medyrax™ Tenant Provisioner Lambda package.

Contains five Lambda handlers that are wired together by the
``mdx-org-provision-sfn`` Step Function (Requirement 8.1, 8.2):

- ``validate``        — validates the provisioning request schema
- ``aws_resources``   — creates per-org KMS key, IAM role, SQS queues,
                        EventBridge bus, and S3 prefixes
- ``healthlake``      — calls AWS HealthLake CreateFHIRDatastore and waits
                        for ACTIVE status
- ``sftp``            — calls AWS Transfer Family CreateServer for per-org
                        SFTP home directory mapping
- ``finalize``        — writes complete tenant record to mdx-tenants DynamoDB
                        and publishes SNS welcome notification
"""
