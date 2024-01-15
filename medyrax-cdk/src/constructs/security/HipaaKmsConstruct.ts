/**
 * HipaaKmsConstruct
 *
 * Creates a per-organisation AWS KMS Customer Managed Key (CMK) with:
 *   - 365-day automatic key rotation (Requirement 7.6)
 *   - Key policy granting access only to specified role ARNs (Requirement 7.1)
 *   - A human-readable alias: alias/mdx-{orgId}-cmk
 *   - 30-day pending deletion window
 *
 * Requirements: 7.1, 7.6
 */
import * as cdk from 'aws-cdk-lib';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface HipaaKmsConstructProps {
  /** Connected_Organization tenant identifier. Key alias: alias/mdx-{orgId}-cmk */
  orgId: string;
  /**
   * Key rotation period in days (default: 365).
   * Note: AWS KMS rotation period can only be set via CfnKey; this prop is
   * kept for documentation purposes — the CDK Key construct always uses
   * annual rotation when enableKeyRotation is true.
   */
  rotationDays?: number;
  /**
   * IAM role ARNs granted kms:Decrypt, kms:GenerateDataKey, kms:DescribeKey.
   * The root account principal is always granted kms:* via the key policy.
   */
  grantedRoleArns?: string[];
  /** AWS account ID used to build the root-account key-policy principal. */
  accountId: string;
}

export class HipaaKmsConstruct extends Construct {
  /** The KMS CMK created for the org. */
  public readonly key: kms.Key;
  /** Convenience shorthand for key.keyArn. */
  public readonly keyArn: string;

  constructor(scope: Construct, id: string, props: HipaaKmsConstructProps) {
    super(scope, id);

    const { orgId, accountId, grantedRoleArns = [] } = props;

    // ── Build the key policy ──────────────────────────────────────────────

    // Statement 1: Allow the account root full admin access (required so the
    // account can always recover the key; standard CDK best practice).
    const rootAdminStatement = new iam.PolicyStatement({
      sid: 'EnableRootAccountAdministration',
      effect: iam.Effect.ALLOW,
      principals: [new iam.AccountRootPrincipal()],
      actions: ['kms:*'],
      resources: ['*'],
    });

    // Statement 2: Grant specified role ARNs usage (decrypt / generate data key).
    const usageStatements: iam.PolicyStatement[] = [];
    if (grantedRoleArns.length > 0) {
      usageStatements.push(
        new iam.PolicyStatement({
          sid: 'GrantOrgRoleUsage',
          effect: iam.Effect.ALLOW,
          principals: grantedRoleArns.map(arn => new iam.ArnPrincipal(arn)),
          actions: [
            'kms:Decrypt',
            'kms:GenerateDataKey',
            'kms:DescribeKey',
          ],
          resources: ['*'],
        }),
      );
    }

    const keyPolicy = new iam.PolicyDocument({
      statements: [rootAdminStatement, ...usageStatements],
    });

    // ── Create the KMS Key ────────────────────────────────────────────────
    this.key = new kms.Key(this, 'OrgCmk', {
      description: `Medyrax per-org CMK for org ${orgId}`,
      enableKeyRotation: true,          // annual rotation (Requirement 7.6)
      policy: keyPolicy,
      pendingWindow: cdk.Duration.days(30),
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // ── Alias ─────────────────────────────────────────────────────────────
    new kms.Alias(this, 'OrgCmkAlias', {
      aliasName: `alias/mdx-${orgId}-cmk`,
      targetKey: this.key,
    });

    this.keyArn = this.key.keyArn;

    // ── CDK Tags ──────────────────────────────────────────────────────────
    cdk.Tags.of(this).add('MdxOrgId', orgId);
    cdk.Tags.of(this).add('MdxComponent', 'KmsCmk');
  }
}
