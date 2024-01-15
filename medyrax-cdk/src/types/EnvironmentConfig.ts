/**
 * @mdx/types — EnvironmentConfig
 *
 * Configuration loaded from {@code config/{env}.json} at CDK synth time.
 *
 * Each environment (dev, staging, prod) has its own JSON config file under
 * {@code medyrax-cdk/config/}.  The CDK app reads the appropriate file based
 * on the {@code --context env=<name>} flag passed to the CDK CLI.
 */
export interface EnvironmentConfig {
  /** AWS account ID for the deployment target. */
  awsAccountId: string;

  /** AWS region for the deployment target (e.g. "us-east-1"). */
  awsRegion: string;

  /** Short environment name: dev | staging | prod. */
  envName: 'dev' | 'staging' | 'prod';

  /**
   * VPC ID to deploy Lambda functions and NLB into.
   * If omitted, the Core Stack creates a new dedicated VPC.
   */
  vpcId?: string;

  /** List of private subnet IDs for Lambda and NLB placement. */
  privateSubnetIds?: string[];

  /** List of public subnet IDs for the NLB (MLLP listener). */
  publicSubnetIds?: string[];

  /** Custom domain name for the API Gateway (e.g. "api.medyrax.example.com"). */
  apiDomainName?: string;

  /** ACM certificate ARN for the custom domain. */
  apiCertificateArn?: string;

  /**
   * Whether to attach AWS WAF to API Gateway.
   * Default: true for staging and prod; false for dev.
   */
  enableWaf?: boolean;

  /**
   * Whether to provision an AWS HealthLake FHIR datastore.
   * HealthLake provisioning takes ~20 min; set false for dev fast-iteration.
   * Default: false for dev; true for staging and prod.
   */
  enableHealthLake?: boolean;

  /**
   * Whether to provision an Amazon MSK (Kafka) cluster for analytics streaming.
   * Default: false for dev.
   */
  enableMsk?: boolean;

  /**
   * Whether to provision an Amazon ElastiCache (Redis) cluster for
   * the Terminology Service hot-path cache.
   * Default: false for dev (uses in-process LRU cache instead).
   */
  enableElastiCache?: boolean;

  /**
   * PagerDuty SNS topic ARN for CRITICAL/HIGH alarms.
   * If omitted, alarms route only to the platform CloudWatch alarm action.
   */
  pagerDutySnsTopicArn?: string;

  /**
   * S3 bucket name for CDK bootstrap asset staging.
   * If omitted, CDK uses the default bootstrap staging bucket.
   */
  cdkAssetBucketName?: string;

  /**
   * Whether to retain DynamoDB tables and S3 buckets when a stack is deleted.
   * Default: true for staging and prod (HIPAA data retention); false for dev.
   */
  retainStatefulResources?: boolean;

  /**
   * Override for the Cognito access token expiry in minutes.
   * Default: 15 (required by Requirement 7.7).
   */
  cognitoAccessTokenExpiryMinutes?: number;

  /**
   * Whether AWS X-Ray active tracing is enabled on all Lambda functions.
   * Default: true for all environments.
   */
  enableXRay?: boolean;

  /**
   * TCP port for the MLLP Listener NLB (default 2575 per HL7 standard).
   */
  mllpPort?: number;

  /**
   * Analytics Firehose buffer interval in minutes (default 30).
   * Requirement 11.5.
   */
  analyticsBufferMinutes?: number;
}
