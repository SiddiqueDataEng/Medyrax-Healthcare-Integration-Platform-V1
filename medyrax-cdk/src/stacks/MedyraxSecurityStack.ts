/**
 * MedyraxSecurityStack
 *
 * CDK Stack that wires together all security-layer constructs:
 *   1. HipaaKmsConstruct  — platform-level CMK (orgId = 'platform')
 *   2. HipaaIamRoles      — five RBAC roles (Platform_Admin → Audit_Reviewer)
 *   3. HipaaAuditTrail    — CloudTrail + S3 7-year audit retention
 *
 * The Integration_Service role is granted CMK usage so it can encrypt/decrypt
 * PHI at rest.
 *
 * Requirements: 7.1, 7.2, 7.4, 7.6, 7.8
 */
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '@mdx/types';
import { HipaaKmsConstruct } from '../constructs/security/HipaaKmsConstruct';
import { HipaaIamRoles } from '../constructs/security/HipaaIamRoles';
import { HipaaAuditTrail } from '../constructs/security/HipaaAuditTrail';

export class MedyraxSecurityStack extends cdk.Stack {
  /** Platform-level CMK (orgId = 'platform'). */
  public readonly platformCmk: HipaaKmsConstruct;
  /** Five RBAC IAM roles. */
  public readonly iamRoles: HipaaIamRoles;
  /** CloudTrail + S3 7-year audit trail. */
  public readonly auditTrail: HipaaAuditTrail;

  constructor(scope: Construct, id: string, props: MedyraxStackProps) {
    super(scope, id, props);

    const { envName } = props;
    // Resolve the account ID — falls back to CDK token at synth time.
    const accountId = this.account;

    // ── 1. Platform CMK ───────────────────────────────────────────────────
    // orgId = 'platform' — shared CMK for the security layer itself.
    // Granted role ARNs are wired after the IAM roles are created below.
    this.platformCmk = new HipaaKmsConstruct(this, 'PlatformCmk', {
      orgId: 'platform',
      accountId,
      rotationDays: 365,
    });

    // ── 2. RBAC IAM Roles ─────────────────────────────────────────────────
    this.iamRoles = new HipaaIamRoles(this, 'IamRoles', {
      envName,
      accountId,
      kmsKeyArn: this.platformCmk.keyArn,
    });

    // ── 3. CloudTrail + Audit S3 Bucket ───────────────────────────────────
    this.auditTrail = new HipaaAuditTrail(this, 'AuditTrail', {
      envName,
    });

    // ── Wire up: grant Integration_Service role CMK usage ─────────────────
    // The HipaaKmsConstruct already grants access via grantedRoleArns, but
    // since the roles were created after the CMK, we use the key.grant* helper
    // to add the grant to the key policy imperatively.
    this.platformCmk.key.grantDecrypt(this.iamRoles.integrationServiceRole);
    this.platformCmk.key.grantEncryptDecrypt(this.iamRoles.integrationServiceRole);

    // ── Stack-level tags ──────────────────────────────────────────────────
    cdk.Tags.of(this).add('Project', 'Medyrax');
    cdk.Tags.of(this).add('Layer', 'Security');
    cdk.Tags.of(this).add('Environment', envName);

    // ── CloudFormation outputs ─────────────────────────────────────────────
    new cdk.CfnOutput(this, 'PlatformCmkArn', {
      value: this.platformCmk.keyArn,
      description: 'Platform KMS CMK ARN',
      exportName: `mdx-platform-cmk-arn-${envName}`,
    });

    new cdk.CfnOutput(this, 'IntegrationServiceRoleArn', {
      value: this.iamRoles.integrationServiceRole.roleArn,
      description: 'Integration Service IAM Role ARN',
      exportName: `mdx-integration-service-role-arn-${envName}`,
    });

    new cdk.CfnOutput(this, 'AuditBucketName', {
      value: this.auditTrail.auditBucket.bucketName,
      description: 'CloudTrail audit S3 bucket name',
      exportName: `mdx-audit-bucket-name-${envName}`,
    });
  }
}
