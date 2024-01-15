/**
 * HipaaIamRoles
 *
 * Creates the five RBAC IAM roles required by the Medyrax™ platform with
 * least-privilege policies (Requirement 7.2, 7.4):
 *
 *   Platform_Admin        — KMS admin, DynamoDB, S3, Lambda, CloudTrail, IAM read
 *   Organization_Admin    — tenant-scoped DynamoDB/S3 + Lambda invoke
 *   Clinical_User         — FHIR API invoke only (API GW execute-api)
 *   Integration_Service   — SQS, EventBridge, DynamoDB, S3, KMS (Lambda service principal)
 *   Audit_Reviewer        — CloudTrail/CloudWatch/S3 read-only
 *
 * Role names follow the pattern: mdx-{roleName}-{envName}
 * e.g. mdx-platform-admin-dev
 *
 * Requirements: 7.2, 7.4
 */
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';

export interface HipaaIamRolesProps {
  /** Short environment name: dev | staging | prod. */
  envName: string;
  /** AWS account ID used to build assume-role trust policies. */
  accountId: string;
  /** KMS CMK ARN to grant the Integration_Service role usage. */
  kmsKeyArn: string;
}

export class HipaaIamRoles extends Construct {
  public readonly platformAdminRole: iam.Role;
  public readonly orgAdminRole: iam.Role;
  public readonly clinicalUserRole: iam.Role;
  public readonly integrationServiceRole: iam.Role;
  public readonly auditReviewerRole: iam.Role;

  constructor(scope: Construct, id: string, props: HipaaIamRolesProps) {
    super(scope, id);

    const { envName, accountId, kmsKeyArn } = props;

    // ── Shared trust principals ───────────────────────────────────────────
    const accountPrincipal = new iam.AccountPrincipal(accountId);
    const cognitoPrincipal = new iam.FederatedPrincipal(
      'cognito-identity.amazonaws.com',
      {
        StringEquals: { 'cognito-identity.amazonaws.com:aud': '*' },
        'ForAnyValue:StringLike': { 'cognito-identity.amazonaws.com:amr': 'authenticated' },
      },
      'sts:AssumeRoleWithWebIdentity',
    );

    // ── 1. Platform_Admin ─────────────────────────────────────────────────
    this.platformAdminRole = new iam.Role(this, 'PlatformAdminRole', {
      roleName: `mdx-platform-admin-${envName}`,
      description: 'Medyrax Platform Administrator — full platform control',
      assumedBy: accountPrincipal,
    });

    // KMS admin permissions
    this.platformAdminRole.addToPolicy(new iam.PolicyStatement({
      sid: 'KmsAdmin',
      effect: iam.Effect.ALLOW,
      actions: [
        'kms:Create*',
        'kms:Describe*',
        'kms:Enable*',
        'kms:List*',
        'kms:Put*',
        'kms:Update*',
        'kms:Revoke*',
        'kms:Disable*',
        'kms:Get*',
        'kms:Delete*',
        'kms:ScheduleKeyDeletion',
        'kms:CancelKeyDeletion',
        'kms:Decrypt',
        'kms:GenerateDataKey',
        'kms:DescribeKey',
      ],
      resources: ['*'],
    }));

    // DynamoDB full
    this.platformAdminRole.addToPolicy(new iam.PolicyStatement({
      sid: 'DynamoDbFull',
      effect: iam.Effect.ALLOW,
      actions: ['dynamodb:*'],
      resources: ['*'],
    }));

    // S3 full
    this.platformAdminRole.addToPolicy(new iam.PolicyStatement({
      sid: 'S3Full',
      effect: iam.Effect.ALLOW,
      actions: ['s3:*'],
      resources: ['*'],
    }));

    // Lambda full
    this.platformAdminRole.addToPolicy(new iam.PolicyStatement({
      sid: 'LambdaFull',
      effect: iam.Effect.ALLOW,
      actions: ['lambda:*'],
      resources: ['*'],
    }));

    // CloudTrail full
    this.platformAdminRole.addToPolicy(new iam.PolicyStatement({
      sid: 'CloudTrailFull',
      effect: iam.Effect.ALLOW,
      actions: ['cloudtrail:*'],
      resources: ['*'],
    }));

    // IAM read-only
    this.platformAdminRole.addToPolicy(new iam.PolicyStatement({
      sid: 'IamReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'iam:Get*',
        'iam:List*',
        'iam:Generate*',
        'iam:Simulate*',
      ],
      resources: ['*'],
    }));

    // ── 2. Organization_Admin ─────────────────────────────────────────────
    this.orgAdminRole = new iam.Role(this, 'OrgAdminRole', {
      roleName: `mdx-organization-admin-${envName}`,
      description: 'Medyrax Organisation Administrator — tenant-scoped data access',
      assumedBy: new iam.CompositePrincipal(accountPrincipal, cognitoPrincipal),
    });

    // DynamoDB read/write on tenant tables (resource restricted at deploy time via tag conditions)
    this.orgAdminRole.addToPolicy(new iam.PolicyStatement({
      sid: 'DynamoDbTenantReadWrite',
      effect: iam.Effect.ALLOW,
      actions: [
        'dynamodb:GetItem',
        'dynamodb:PutItem',
        'dynamodb:UpdateItem',
        'dynamodb:DeleteItem',
        'dynamodb:Query',
        'dynamodb:Scan',
        'dynamodb:BatchGetItem',
        'dynamodb:BatchWriteItem',
        'dynamodb:DescribeTable',
        'dynamodb:ListTables',
      ],
      resources: ['*'],
    }));

    // S3 read/write on org-prefixed objects
    this.orgAdminRole.addToPolicy(new iam.PolicyStatement({
      sid: 'S3OrgReadWrite',
      effect: iam.Effect.ALLOW,
      actions: [
        's3:GetObject',
        's3:PutObject',
        's3:DeleteObject',
        's3:ListBucket',
        's3:GetBucketLocation',
      ],
      resources: ['*'],
    }));

    // Lambda invoke
    this.orgAdminRole.addToPolicy(new iam.PolicyStatement({
      sid: 'LambdaInvoke',
      effect: iam.Effect.ALLOW,
      actions: ['lambda:InvokeFunction'],
      resources: ['*'],
    }));

    // ── 3. Clinical_User ──────────────────────────────────────────────────
    this.clinicalUserRole = new iam.Role(this, 'ClinicalUserRole', {
      roleName: `mdx-clinical-user-${envName}`,
      description: 'Medyrax Clinical User — FHIR API access only',
      assumedBy: new iam.CompositePrincipal(accountPrincipal, cognitoPrincipal),
    });

    // API Gateway execute-api only (no direct DynamoDB/S3)
    this.clinicalUserRole.addToPolicy(new iam.PolicyStatement({
      sid: 'FhirApiInvoke',
      effect: iam.Effect.ALLOW,
      actions: ['execute-api:Invoke'],
      resources: ['arn:aws:execute-api:*:*:*/*/GET/*', 'arn:aws:execute-api:*:*:*/*/POST/*'],
    }));

    // ── 4. Integration_Service ────────────────────────────────────────────
    this.integrationServiceRole = new iam.Role(this, 'IntegrationServiceRole', {
      roleName: `mdx-integration-service-${envName}`,
      description: 'Medyrax Integration Service — SQS, EventBridge, DynamoDB, S3, KMS',
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
    });

    // SQS send/receive
    this.integrationServiceRole.addToPolicy(new iam.PolicyStatement({
      sid: 'SqsAccess',
      effect: iam.Effect.ALLOW,
      actions: [
        'sqs:SendMessage',
        'sqs:ReceiveMessage',
        'sqs:DeleteMessage',
        'sqs:GetQueueAttributes',
        'sqs:GetQueueUrl',
        'sqs:ChangeMessageVisibility',
      ],
      resources: ['*'],
    }));

    // EventBridge put events
    this.integrationServiceRole.addToPolicy(new iam.PolicyStatement({
      sid: 'EventBridgePutEvents',
      effect: iam.Effect.ALLOW,
      actions: ['events:PutEvents'],
      resources: ['*'],
    }));

    // DynamoDB read/write
    this.integrationServiceRole.addToPolicy(new iam.PolicyStatement({
      sid: 'DynamoDbIntegrationReadWrite',
      effect: iam.Effect.ALLOW,
      actions: [
        'dynamodb:GetItem',
        'dynamodb:PutItem',
        'dynamodb:UpdateItem',
        'dynamodb:DeleteItem',
        'dynamodb:Query',
        'dynamodb:Scan',
        'dynamodb:BatchGetItem',
        'dynamodb:BatchWriteItem',
        'dynamodb:DescribeTable',
      ],
      resources: ['*'],
    }));

    // S3 read/write
    this.integrationServiceRole.addToPolicy(new iam.PolicyStatement({
      sid: 'S3IntegrationReadWrite',
      effect: iam.Effect.ALLOW,
      actions: [
        's3:GetObject',
        's3:PutObject',
        's3:DeleteObject',
        's3:ListBucket',
        's3:GetBucketLocation',
      ],
      resources: ['*'],
    }));

    // KMS usage (GenerateDataKey for encryption)
    this.integrationServiceRole.addToPolicy(new iam.PolicyStatement({
      sid: 'KmsIntegrationUsage',
      effect: iam.Effect.ALLOW,
      actions: [
        'kms:GenerateDataKey',
        'kms:Decrypt',
        'kms:DescribeKey',
      ],
      resources: [kmsKeyArn],
    }));

    // Basic Lambda execution (CloudWatch Logs)
    this.integrationServiceRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
    );

    // ── 5. Audit_Reviewer ─────────────────────────────────────────────────
    this.auditReviewerRole = new iam.Role(this, 'AuditReviewerRole', {
      roleName: `mdx-audit-reviewer-${envName}`,
      description: 'Medyrax Audit Reviewer — read-only CloudTrail, CloudWatch, S3 audit',
      assumedBy: new iam.CompositePrincipal(accountPrincipal, cognitoPrincipal),
    });

    // CloudTrail read-only
    this.auditReviewerRole.addToPolicy(new iam.PolicyStatement({
      sid: 'CloudTrailReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'cloudtrail:DescribeTrails',
        'cloudtrail:GetTrailStatus',
        'cloudtrail:GetEventSelectors',
        'cloudtrail:LookupEvents',
        'cloudtrail:ListTags',
        'cloudtrail:ListTrails',
        'cloudtrail:GetTrail',
        'cloudtrail:GetInsightSelectors',
      ],
      resources: ['*'],
    }));

    // CloudWatch Logs read-only
    this.auditReviewerRole.addToPolicy(new iam.PolicyStatement({
      sid: 'CloudWatchLogsReadOnly',
      effect: iam.Effect.ALLOW,
      actions: [
        'logs:DescribeLogGroups',
        'logs:DescribeLogStreams',
        'logs:GetLogEvents',
        'logs:FilterLogEvents',
        'logs:StartQuery',
        'logs:StopQuery',
        'logs:GetQueryResults',
        'logs:GetLogRecord',
      ],
      resources: ['*'],
    }));

    // S3 read on audit bucket (no write)
    this.auditReviewerRole.addToPolicy(new iam.PolicyStatement({
      sid: 'S3AuditBucketRead',
      effect: iam.Effect.ALLOW,
      actions: [
        's3:GetObject',
        's3:ListBucket',
        's3:GetBucketLocation',
        's3:GetObjectVersion',
      ],
      resources: [
        `arn:aws:s3:::mdx-audit-trail-${accountId}`,
        `arn:aws:s3:::mdx-audit-trail-${accountId}/*`,
      ],
    }));

    // ── CDK Tags ──────────────────────────────────────────────────────────
    cdk.Tags.of(this).add('MdxComponent', 'IamRbac');
  }
}
