/**
 * @mdx/types — CDK Construct Props Interfaces
 *
 * Defines the TypeScript prop interfaces for every reusable CDK construct in
 * the Medyrax™ platform.  These are co-located here so all stacks import from
 * a single source of truth.
 *
 * Design reference § 15 (IaC):
 *   - HipaaCompliantBucket  — S3 + SSE-KMS + enforce-encryption bucket policy
 *   - TenantIsolatedQueue   — SQS FIFO + per-org CMK
 *   - FhirLambda            — Lambda + X-Ray + VPC + least-privilege IAM
 *   - AuditableApi          — API Gateway + WAF + CloudWatch Logs
 *   - HipaaKmsConstruct     — per-org CMK + 365-day rotation
 *   - TenantEventBus        — EventBridge custom bus per org
 */

import * as cdk from 'aws-cdk-lib';
import { EnvironmentConfig } from './EnvironmentConfig';

// ── Base stack props ──────────────────────────────────────────────────────────

/**
 * Base props shared by all Medyrax™ CDK stacks.
 * Every stack extends this to receive the environment context.
 */
export interface MedyraxStackProps extends cdk.StackProps {
  /** Short environment name: dev | staging | prod. */
  envName: string;
  /** Full environment configuration loaded from config/{env}.json. */
  envConfig: EnvironmentConfig;
}

// ── HipaaCompliantBucket ──────────────────────────────────────────────────────

/**
 * Props for the {@code HipaaCompliantBucket} CDK construct.
 *
 * Creates an S3 bucket with SSE-KMS encryption, block-public-access,
 * versioning, and a deny-unencrypted-uploads bucket policy as required by
 * HIPAA security controls (Requirement 7.1, 7.8).
 */
export interface HipaaCompliantBucketProps {
  /**
   * Logical name prefix used to form the bucket name.
   * Resulting name: {@code ${bucketNamePrefix}-${awsAccountId}}.
   */
  bucketNamePrefix: string;
  /** KMS CMK ARN used for SSE-KMS bucket encryption. */
  kmsKeyArn: string;
  /** Enable S3 versioning (default: true). */
  versioned?: boolean;
  /**
   * Transition objects to S3 Glacier after N days.
   * Use for audit-log buckets requiring 7-year HIPAA retention (Req 7.8).
   */
  archiveAfterDays?: number;
  /** Target S3 bucket ARN for server access logging. */
  serverAccessLogsBucketArn?: string;
  /**
   * CloudFormation removal policy.
   * Default: {@code RETAIN} (prevents accidental data deletion in prod).
   */
  removalPolicy?: cdk.RemovalPolicy;
}

// ── TenantIsolatedQueue ───────────────────────────────────────────────────────

/**
 * Props for the {@code TenantIsolatedQueue} CDK construct.
 *
 * Creates an SQS FIFO queue encrypted with the org's CMK and backed by a DLQ
 * that triggers a CloudWatch alarm when depth exceeds 100 messages (Req 5.4).
 */
export interface TenantIsolatedQueueProps {
  /** Connected_Organization tenant identifier (used in queue name). */
  orgId: string;
  /**
   * Queue name suffix, e.g. "hl7-inbound", "fhir-queue", "webhook".
   * Full queue name: {@code mdx-${orgId}-${queueNameSuffix}.fifo}.
   */
  queueNameSuffix: string;
  /** KMS CMK ARN for SQS server-side encryption. */
  kmsKeyArn: string;
  /**
   * Whether to create a FIFO queue (default: true).
   * All Integration Bus queues are FIFO for per-patient ordering.
   */
  fifo?: boolean;
  /**
   * Visibility timeout in seconds (default: 300).
   * Should be ≥ 6× the consumer Lambda timeout to avoid duplicate delivery.
   */
  visibilityTimeoutSeconds?: number;
  /**
   * Maximum receive count before routing to the DLQ (default: 3).
   * Requirement 5.4: route to DLQ after 3 failed delivery attempts.
   */
  maxReceiveCount?: number;
}

// ── FhirLambda ────────────────────────────────────────────────────────────────

/**
 * Props for the {@code FhirLambda} CDK construct.
 *
 * Wraps an AWS Lambda function with X-Ray active tracing, VPC placement,
 * and least-privilege IAM as required by Requirement 7.2.
 */
export interface FhirLambdaProps {
  /**
   * Lambda function name (e.g. "fhir-engine-validate", "hl7-parser").
   * Used as both the CDK logical ID and the AWS function name.
   */
  functionName: string;
  /**
   * Path to the Lambda deployment package relative to the CDK project root.
   * For Python Lambdas this is the zipped {@code .zip} asset path.
   */
  assetPath: string;
  /**
   * Lambda handler entry point.
   * Python: {@code "module.handler"} — e.g. {@code "fhir_engine.validate.handler"}.
   */
  handler: string;
  /** Lambda runtime (default: {@code python3.12}). */
  runtime?: 'python3.12' | 'nodejs20.x';
  /** Memory allocation in MB (default: 512). */
  memoryMb?: number;
  /** Function timeout in seconds (default: 30). */
  timeoutSeconds?: number;
  /** Additional environment variables injected into the Lambda. */
  environment?: Record<string, string>;
  /**
   * Whether AWS X-Ray active tracing is enabled (default: true).
   * Requirement 14 (Observability).
   */
  enableTracing?: boolean;
  /** KMS CMK ARN for encrypting Lambda environment variables. */
  kmsKeyArn?: string;
  /** VPC private subnet IDs for VPC placement. */
  vpcSubnetIds?: string[];
  /** Security group IDs to attach to the Lambda ENI. */
  securityGroupIds?: string[];
  /** Lambda Layers ARNs to attach (e.g. fhir.resources layer). */
  layerArns?: string[];
}

// ── AuditableApi ─────────────────────────────────────────────────────────────

/**
 * Props for the {@code AuditableApi} CDK construct.
 *
 * Creates an API Gateway REST API with WAF, CloudWatch access logging, and
 * Cognito JWT authorizer as required by the API Gateway Layer design (§ 6).
 */
export interface AuditableApiProps {
  /** API Gateway logical name. */
  apiName: string;
  /** Custom domain name (e.g. "api.medyrax.example.com"). */
  domainName?: string;
  /** ACM certificate ARN for the custom domain. */
  certificateArn?: string;
  /**
   * Whether to attach AWS WAF with the OWASP rule set (default: true
   * for staging/prod; false for dev).
   */
  enableWaf?: boolean;
  /** Cognito User Pool ARN for the JWT authorizer. */
  cognitoUserPoolArn?: string;
  /** CloudWatch Logs log group ARN for API access logging. */
  accessLogGroupArn?: string;
  /**
   * Usage plan throttle burst limit per API key (Connected_Organization).
   * Default: 1000 requests per minute (Requirement 6.4).
   */
  throttlingBurstLimit?: number;
  /** Usage plan rate limit (requests per second). Default: 17 ≈ 1000/min. */
  throttlingRateLimit?: number;
}

// ── HipaaKmsConstruct ─────────────────────────────────────────────────────────

/**
 * Props for the {@code HipaaKmsConstruct} CDK construct.
 *
 * Creates a per-org AWS KMS CMK with 365-day automatic rotation.
 * Requirement 7.6 — key rotation; Requirement 7.1 — per-org CMK.
 */
export interface HipaaKmsConstructProps {
  /** Connected_Organization tenant identifier. Key alias: {@code mdx-${orgId}-cmk}. */
  orgId: string;
  /**
   * Key rotation period in days (default: 365).
   * Configurable per-org via tenant config (Requirement 7.6).
   */
  rotationDays?: number;
  /**
   * IAM role ARNs that are granted {@code kms:Decrypt} and {@code kms:GenerateDataKey}
   * on this CMK.  The Platform_Admin role is always granted access implicitly.
   */
  grantedRoleArns?: string[];
}

// ── TenantEventBus ────────────────────────────────────────────────────────────

/**
 * Props for the {@code TenantEventBus} CDK construct.
 *
 * Creates an EventBridge custom bus per org with routing rules for each FHIR
 * resource type, a 90-day event archive, and a DLQ alarm.
 * Requirements 5.1, 5.4, 5.5.
 */
export interface TenantEventBusProps {
  /** Connected_Organization tenant identifier.  Bus name: {@code mdx-${orgId}-bus}. */
  orgId: string;
  /** KMS CMK ARN for encrypting the EventBridge archive S3 destination. */
  kmsKeyArn: string;
  /**
   * Retention days for the EventBridge event archive (default: 90).
   * Events older than this are automatically purged from the archive.
   */
  archiveRetentionDays?: number;
  /**
   * CloudWatch alarm SNS topic ARN for DLQ depth > 100 alerts.
   * Requirement 5.4.
   */
  alarmSnsTopicArn?: string;
}
