import * as cdk from 'aws-cdk-lib';
import { EnvironmentConfig } from './EnvironmentConfig';

/**
 * Base props shared by all Medyrax™ CDK stacks.
 */
export interface MedyraxStackProps extends cdk.StackProps {
  /** Short environment name (dev | staging | prod). */
  envName: string;
  /** Full environment configuration loaded from config/{env}.json. */
  envConfig: EnvironmentConfig;
}

/**
 * Props for the {@code HipaaCompliantBucket} construct.
 *
 * Design reference: "HipaaCompliantBucket CDK construct:
 * S3 bucket with SSE-KMS, block public access, versioning,
 * deny-unencrypted uploads bucket policy"
 */
export interface HipaaCompliantBucketProps {
  /** Logical ID prefix used to name the bucket (e.g. "hb-{orgId}-inbound"). */
  bucketNamePrefix: string;
  /** KMS key ARN for SSE-KMS encryption. */
  kmsKeyArn: string;
  /** Whether to enable S3 Versioning (default true). */
  versioned?: boolean;
  /**
   * S3 lifecycle rule to transition objects to Glacier after N days.
   * Use for audit log buckets requiring 7-year HIPAA retention.
   */
  archiveAfterDays?: number;
  /** Enable S3 server access logging to a target bucket. */
  serverAccessLogsBucketArn?: string;
  /** CloudFormation removal policy (default: RETAIN for prod). */
  removalPolicy?: cdk.RemovalPolicy;
}

/**
 * Props for the {@code TenantIsolatedQueue} construct.
 *
 * Design reference: "TenantIsolatedQueue: SQS FIFO + per-org KMS"
 */
export interface TenantIsolatedQueueProps {
  /** Connected_Organization tenant identifier. */
  orgId: string;
  /** Logical queue name suffix (e.g. "hl7-inbound", "fhir-queue"). */
  queueNameSuffix: string;
  /** KMS key ARN for SQS SSE-KMS encryption. */
  kmsKeyArn: string;
  /**
   * Whether this is a FIFO queue (default true).
   * All SQS queues in the Integration Bus are FIFO.
   */
  fifo?: boolean;
  /**
   * Visibility timeout in seconds (default 300).
   * Should be at least 6× the Lambda function timeout.
   */
  visibilityTimeoutSeconds?: number;
  /**
   * Maximum receive count before a message is routed to the DLQ (default 3).
   * Requirement 5.4: after 3 delivery attempts, route to DLQ.
   */
  maxReceiveCount?: number;
}

/**
 * Props for the {@code FhirLambda} construct.
 *
 * Design reference: "FhirLambda: Lambda + X-Ray + VPC + least-privilege"
 */
export interface FhirLambdaProps {
  /** Lambda function name (e.g. "fhir-engine-validate"). */
  functionName: string;
  /** Path to the JAR artifact relative to the CDK project root. */
  jarAssetPath: string;
  /** Java handler class (e.g. "com.Medyrax.fhir.FhirValidateHandler::handleRequest"). */
  handler: string;
  /** Memory allocation in MB (default 512). */
  memoryMb?: number;
  /** Timeout in seconds (default 30). */
  timeoutSeconds?: number;
  /** Additional environment variables injected into the Lambda. */
  environment?: Record<string, string>;
  /** Whether X-Ray active tracing is enabled (default true). */
  enableTracing?: boolean;
  /** KMS key ARN for environment variable encryption. */
  kmsKeyArn?: string;
  /** VPC subnet IDs for VPC placement. */
  vpcSubnetIds?: string[];
  /** Security group IDs to attach. */
  securityGroupIds?: string[];
}

/**
 * Props for the {@code AuditableApi} construct.
 *
 * Design reference: "AuditableApi: API GW + WAF + CloudWatch Logs"
 */
export interface AuditableApiProps {
  /** API Gateway name. */
  apiName: string;
  /** Custom domain name (optional). */
  domainName?: string;
  /** ACM certificate ARN for custom domain. */
  certificateArn?: string;
  /** Whether to attach AWS WAF (default true for staging/prod). */
  enableWaf?: boolean;
  /** Cognito User Pool ARN for JWT authorizer. */
  cognitoUserPoolArn?: string;
  /** CloudWatch Logs log group ARN for access logging. */
  accessLogGroupArn?: string;
}

/**
 * Props for the {@code HipaaKmsConstruct}.
 *
 * Design reference (Security Stack):
 * "Create HipaaKmsConstruct: per-org CMK with 365-day auto-rotation"
 */
export interface HipaaKmsConstructProps {
  /** Connected_Organization tenant identifier. */
  orgId: string;
  /** Key rotation period in days (default 365). Requirement 7.6. */
  rotationDays?: number;
  /**
   * IAM role ARNs that should have access to use/decrypt with this key.
   * The platform admin role is always granted access implicitly.
   */
  grantedRoleArns?: string[];
}
