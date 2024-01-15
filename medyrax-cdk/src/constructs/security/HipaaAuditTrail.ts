/**
 * HipaaAuditTrail
 *
 * Creates an AWS CloudTrail trail writing to a dedicated S3 bucket with
 * 7-year retention (Requirement 7.8):
 *
 *   - S3 bucket: mdx-audit-trail-{accountId}
 *   - SSE-S3 bucket encryption, block public access, versioning enabled
 *   - S3 lifecycle: GLACIER after 90 days, expire after 2555 days (7 years)
 *   - CloudTrail: multi-region, global service events, log-file validation
 *   - Trail name: mdx-platform-audit-trail-{envName}
 *
 * Requirements: 7.8
 */
import * as cdk from 'aws-cdk-lib';
import * as cloudtrail from 'aws-cdk-lib/aws-cloudtrail';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface HipaaAuditTrailProps {
  /** Short environment name: dev | staging | prod. */
  envName: string;
}

export class HipaaAuditTrail extends Construct {
  /** The CloudTrail trail resource. */
  public readonly trail: cloudtrail.Trail;
  /** The S3 bucket receiving all CloudTrail log files. */
  public readonly auditBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: HipaaAuditTrailProps) {
    super(scope, id);

    const { envName } = props;

    // ── S3 audit bucket ───────────────────────────────────────────────────
    // Name uses cdk.Aws.ACCOUNT_ID token so it resolves at deploy time.
    this.auditBucket = new s3.Bucket(this, 'AuditBucket', {
      bucketName: `mdx-audit-trail-${cdk.Aws.ACCOUNT_ID}`,

      // SSE-S3 — CloudTrail manages its own encryption on top of this
      encryption: s3.BucketEncryption.S3_MANAGED,

      // Block all public access (HIPAA requirement)
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,

      // Versioning enabled for immutability assurance
      versioned: true,

      // Retain the bucket if the stack is deleted (HIPAA data retention)
      removalPolicy: cdk.RemovalPolicy.RETAIN,

      // Enforce HTTPS-only access
      enforceSSL: true,

      // 7-year retention lifecycle
      lifecycleRules: [
        {
          id: 'HipaaSevenYearRetention',
          enabled: true,
          // Transition to GLACIER after 90 days (cost optimisation)
          transitions: [
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
          // Expire after 7 years = 2555 days
          expiration: cdk.Duration.days(2555),
          // Also expire non-current versions to control storage cost
          noncurrentVersionExpiration: cdk.Duration.days(2555),
        },
      ],
    });

    // ── CloudTrail trail ──────────────────────────────────────────────────
    this.trail = new cloudtrail.Trail(this, 'PlatformTrail', {
      trailName: `mdx-platform-audit-trail-${envName}`,
      bucket: this.auditBucket,

      // Multi-region: captures API activity in all regions
      isMultiRegionTrail: true,

      // Include IAM and global service events (e.g. STS AssumeRole)
      includeGlobalServiceEvents: true,

      // Validate log file integrity (tamper detection)
      enableFileValidation: true,

      // Send management events (read + write)
      managementEvents: cloudtrail.ReadWriteType.ALL,

      // Retain CloudFormation resource on stack delete
      sendToCloudWatchLogs: false,
    });

    // ── CDK Tags ──────────────────────────────────────────────────────────
    cdk.Tags.of(this).add('MdxComponent', 'AuditTrail');
  }
}
