import * as cdk from 'aws-cdk-lib';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cloudtrail from 'aws-cdk-lib/aws-cloudtrail';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '@mdx/types';

/**
 * Medyrax™ Security Stack
 *
 * Provisions all platform-level security resources:
 * - Platform Admin KMS CMK (used to encrypt the de-identification mapping table)
 * - Five RBAC IAM roles: Platform_Admin, Organization_Admin, Clinical_User,
 *   Integration_Service, Audit_Reviewer (Requirement 7.4)
 * - CloudTrail trail with S3 + 7-year lifecycle retention (Requirement 7.8)
 *
 * Per-org KMS keys are provisioned by the Tenant Stack during onboarding
 * (Requirement 8.2), not here. This stack provides the platform-wide CMK.
 *
 * Task 2.1 implements the full construct implementations; this scaffold
 * provides the stack structure and exported ARNs consumed by downstream stacks.
 */
export class MedyraxSecurityStack extends cdk.Stack {

  /** ARN of the platform-level KMS CMK (used for cross-org resources). */
  public readonly platformAdminKeyArn: string;

  /** ARN of the Platform_Admin IAM role. */
  public readonly platformAdminRoleArn: string;

  /** ARN of the Integration_Service IAM role (used by Lambda execution). */
  public readonly integrationServiceRoleArn: string;

  /** ARN of the Audit_Reviewer IAM role. */
  public readonly auditReviewerRoleArn: string;

  /** Name of the S3 bucket receiving CloudTrail logs. */
  public readonly auditTrailBucketName: string;

  /** ARN of the CloudWatch Logs group for application-level PHI audit events. */
  public readonly auditLogGroupArn: string;

  constructor(scope: Construct, id: string, props: MedyraxStackProps) {
    super(scope, id, props);

    const { envName, envConfig } = props;

    // ── Platform Admin KMS CMK ────────────────────────────────────────────────
    // Used to encrypt:
    //   - mdx-deident-mapping DynamoDB table (Task 18.1)
    //   - Shared platform-level secrets
    // Per-org CMKs are created in the Tenant Stack.
    const platformAdminKey = new kms.Key(this, 'PlatformAdminKey', {
      alias:              `mdx-platform-admin-cmk-${envName}`,
      description:        'Medyrax™ platform-level CMK for cross-org encryption',
      enableKeyRotation:  true,
      rotationSchedule:   kms.RotationSchedule.cron({ day: '1', hour: '0', minute: '0' }),
      removalPolicy:      envName === 'prod'
                            ? cdk.RemovalPolicy.RETAIN
                            : cdk.RemovalPolicy.DESTROY,
      pendingWindow:      cdk.Duration.days(7),
    });

    this.platformAdminKeyArn = platformAdminKey.keyArn;

    // ── CloudTrail audit bucket (7-year lifecycle — Requirement 7.8) ──────────
    const auditTrailBucket = new s3.Bucket(this, 'AuditTrailBucket', {
      bucketName:           `mdx-audit-trail-${this.account}-${envName}`,
      encryption:           s3.BucketEncryption.KMS,
      encryptionKey:        platformAdminKey,
      blockPublicAccess:    s3.BlockPublicAccess.BLOCK_ALL,
      versioned:            true,
      enforceSSL:           true,
      removalPolicy:        cdk.RemovalPolicy.RETAIN,   // Always RETAIN for audit trail
      lifecycleRules: [
        {
          // HIPAA 7-year minimum retention (Requirement 7.8)
          transitions: [
            {
              storageClass:    s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(365),  // Move to Glacier after 1 year
            },
            {
              storageClass:    s3.StorageClass.DEEP_ARCHIVE,
              transitionAfter: cdk.Duration.days(730),  // Move to Deep Archive after 2 years
            },
          ],
          expiration: cdk.Duration.days(2557),  // ~7 years (365 × 7)
        },
      ],
    });

    this.auditTrailBucketName = auditTrailBucket.bucketName;

    // ── CloudWatch Logs group for PHI application-level audit events ──────────
    // Requirement 7.3: audit entries written within 1 second of PHI access
    const auditLogGroup = new logs.LogGroup(this, 'AuditLogGroup', {
      logGroupName:  `/Medyrax/${envName}/audit`,
      retention:     logs.RetentionDays.SEVEN_YEARS,   // Requirement 7.8
      encryptionKey: platformAdminKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    this.auditLogGroupArn = auditLogGroup.logGroupArn;

    // ── CloudTrail trail ──────────────────────────────────────────────────────
    const trail = new cloudtrail.Trail(this, 'AuditTrail', {
      trailName:          `mdx-audit-trail-${envName}`,
      bucket:             auditTrailBucket,
      sendToCloudWatchLogs: true,
      cloudWatchLogsGroup: auditLogGroup,
      enableFileValidation: true,
      isMultiRegionTrail:  false,
      includeGlobalServiceEvents: true,
      managementEvents:    cloudtrail.ReadWriteType.ALL,
    });

    // ── IAM RBAC Roles (Requirement 7.4) ──────────────────────────────────────
    // Full policy attachments are done in Task 2.1 (MedyraxSecurityStack full impl).
    // Here we create the role shells so other stacks can reference their ARNs.

    // 1. Platform_Admin — full read/write, key management
    const platformAdminRole = new iam.Role(this, 'PlatformAdminRole', {
      roleName:     `mdx-platform-admin-role-${envName}`,
      assumedBy:    new iam.ServicePrincipal('lambda.amazonaws.com'),
      description:  'Medyrax Platform_Admin: full read/write access to all resources',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AWSXRayDaemonWriteAccess'),
      ],
    });
    platformAdminKey.grantAdmin(platformAdminRole);
    this.platformAdminRoleArn = platformAdminRole.roleArn;

    // 2. Organization_Admin — CRUD own-org resources, view audit logs
    new iam.Role(this, 'OrgAdminRole', {
      roleName:    `mdx-org-admin-role-${envName}`,
      assumedBy:   new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Medyrax Organization_Admin: manage own-org resources',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // 3. Clinical_User — read PHI, create Observations
    new iam.Role(this, 'ClinicalUserRole', {
      roleName:    `mdx-clinical-user-role-${envName}`,
      assumedBy:   new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Medyrax Clinical_User: read PHI and create Observations',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    // 4. Integration_Service — read/write Integration Bus, call HealthLake
    const integrationServiceRole = new iam.Role(this, 'IntegrationServiceRole', {
      roleName:    `mdx-integration-svc-role-${envName}`,
      assumedBy:   new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Medyrax Integration_Service: Lambda execution role for all data-plane Lambdas',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaVPCAccessExecutionRole'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('AWSXRayDaemonWriteAccess'),
      ],
    });
    this.integrationServiceRoleArn = integrationServiceRole.roleArn;

    // 5. Audit_Reviewer — read-only CloudTrail and CloudWatch Logs
    const auditReviewerRole = new iam.Role(this, 'AuditReviewerRole', {
      roleName:    `mdx-audit-reviewer-role-${envName}`,
      assumedBy:   new iam.AccountPrincipal(this.account),
      description: 'Medyrax Audit_Reviewer: read-only audit log access',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AWSCloudTrailReadOnlyAccess'),
        iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchLogsReadOnlyAccess'),
      ],
    });
    this.auditReviewerRoleArn = auditReviewerRole.roleArn;

    // Allow Audit_Reviewer to decrypt audit logs
    platformAdminKey.grantDecrypt(auditReviewerRole);

    // ── CloudFormation Outputs ────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'PlatformAdminKeyArn', {
      value:       platformAdminKey.keyArn,
      description: 'Platform-level KMS CMK ARN',
      exportName:  `MDX-PlatformAdminKeyArn-${envName}`,
    });

    new cdk.CfnOutput(this, 'AuditTrailBucketName', {
      value:       auditTrailBucket.bucketName,
      description: 'CloudTrail audit trail S3 bucket name',
      exportName:  `MDX-AuditTrailBucketName-${envName}`,
    });

    new cdk.CfnOutput(this, 'AuditLogGroupArn', {
      value:       auditLogGroup.logGroupArn,
      description: 'CloudWatch Logs group ARN for PHI audit events',
      exportName:  `MDX-AuditLogGroupArn-${envName}`,
    });

    cdk.Tags.of(trail).add('HIPAA', 'AuditLog');
    cdk.Tags.of(auditTrailBucket).add('HIPAA', 'AuditLog');
    cdk.Tags.of(platformAdminKey).add('HIPAA', 'CMK');
  }
}
