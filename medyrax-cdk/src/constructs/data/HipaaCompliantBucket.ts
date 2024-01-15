/**
 * HipaaCompliantBucket
 *
 * Reusable CDK construct that creates an S3 bucket configured to HIPAA
 * standards (Requirements 7.1, 7.8, 9.7):
 *
 *   - SSE-KMS encryption with the caller-supplied CMK
 *   - Block all public access
 *   - Versioning enabled
 *   - Deny unencrypted uploads bucket policy (enforces SSE-KMS on every PutObject)
 *   - HTTPS-only access enforcement (denies HTTP)
 *   - Optional: lifecycle archiving to Glacier and object expiration
 *   - Optional: server-access logging target
 *
 * Requirements: 7.1, 7.8, 9.7
 */
import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';
import { HipaaCompliantBucketProps } from '@mdx/types';

export class HipaaCompliantBucket extends Construct {
  /** The underlying S3 Bucket resource. */
  public readonly bucket: s3.Bucket;
  /** Convenience shorthand for bucket.bucketArn. */
  public readonly bucketArn: string;
  /** Convenience shorthand for bucket.bucketName. */
  public readonly bucketName: string;

  constructor(scope: Construct, id: string, props: HipaaCompliantBucketProps) {
    super(scope, id);

    const {
      bucketNamePrefix,
      kmsKeyArn,
      versioned = true,
      archiveAfterDays,
      serverAccessLogsBucketArn,
      removalPolicy = cdk.RemovalPolicy.RETAIN,
    } = props;

    // ── Resolve the KMS key object from its ARN ───────────────────────────
    // We need the IKey interface for the bucket encryption config.
    const kmsKey = kms.Key.fromKeyArn(this, 'BucketCmk', kmsKeyArn);

    // ── Build optional lifecycle rules ────────────────────────────────────
    const lifecycleRules: s3.LifecycleRule[] = [];
    if (archiveAfterDays !== undefined) {
      lifecycleRules.push({
        id: 'HipaaRetentionArchive',
        enabled: true,
        transitions: [
          {
            storageClass: s3.StorageClass.GLACIER,
            transitionAfter: cdk.Duration.days(archiveAfterDays),
          },
        ],
        // Hard-coded 7-year (2555 days) expiration for HIPAA retention
        expiration: cdk.Duration.days(2555),
        noncurrentVersionExpiration: cdk.Duration.days(2555),
      });
    }

    // ── Build optional server-access logging destination ──────────────────
    let serverAccessLogsProps: Partial<s3.BucketProps> = {};
    if (serverAccessLogsBucketArn !== undefined) {
      const logBucket = s3.Bucket.fromBucketArn(
        this,
        'AccessLogsBucket',
        serverAccessLogsBucketArn,
      );
      serverAccessLogsProps = { serverAccessLogsBucket: logBucket };
    }

    // ── Create the S3 bucket ──────────────────────────────────────────────
    this.bucket = new s3.Bucket(this, 'Bucket', {
      // Name: <prefix>-<accountId> (resolved at deploy time via CDK token)
      bucketName: `${bucketNamePrefix}-${cdk.Aws.ACCOUNT_ID}`,

      // SSE-KMS with the caller-supplied org CMK
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: kmsKey,
      // Enforce that the bucket key optimization is NOT used — every object
      // gets its own data key (required for per-object audit granularity).
      bucketKeyEnabled: false,

      // Block all forms of public access (HIPAA requirement)
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,

      // Versioning enabled by default (supports HIPAA audit trail)
      versioned,

      // Enforce HTTPS-only access
      enforceSSL: true,

      lifecycleRules,

      removalPolicy,

      ...serverAccessLogsProps,
    });

    // ── Deny-unencrypted-uploads bucket policy ────────────────────────────
    // Reject any PutObject that does NOT specify SSE-KMS encryption header.
    // This is a belt-and-suspenders control on top of the default bucket encryption.
    this.bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'DenyUnencryptedObjectUploads',
        effect: iam.Effect.DENY,
        principals: [new iam.StarPrincipal()],
        actions: ['s3:PutObject'],
        resources: [this.bucket.arnForObjects('*')],
        conditions: {
          // Deny if the server-side encryption header is absent or not 'aws:kms'
          StringNotEquals: {
            's3:x-amz-server-side-encryption': 'aws:kms',
          },
        },
      }),
    );

    // ── Deny if KMS key ID is wrong (belt-and-suspenders per-org isolation) ─
    // Only objects encrypted with the exact org CMK are accepted.
    this.bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'DenyWrongKmsKey',
        effect: iam.Effect.DENY,
        principals: [new iam.StarPrincipal()],
        actions: ['s3:PutObject'],
        resources: [this.bucket.arnForObjects('*')],
        conditions: {
          StringNotEquals: {
            's3:x-amz-server-side-encryption-aws-kms-key-id': kmsKeyArn,
          },
        },
      }),
    );

    this.bucketArn = this.bucket.bucketArn;
    this.bucketName = this.bucket.bucketName;

    // ── CDK Tags ──────────────────────────────────────────────────────────
    cdk.Tags.of(this).add('MdxComponent', 'HipaaCompliantBucket');
    cdk.Tags.of(this).add('MdxBucketPrefix', bucketNamePrefix);
  }
}
