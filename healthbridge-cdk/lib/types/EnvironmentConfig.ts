/**
 * EnvironmentConfig — Configuration loaded from config/{env}.json.
 *
 * Each environment (dev, staging, prod) has its own JSON config file under
 * Medyrax-cdk/config/. The CDK app reads the appropriate file based on
 * the --context env=<name> flag.
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
   * If undefined, a new VPC is created by the Core Stack.
   */
  vpcId?: string;

  /** List of private subnet IDs for Lambda and NLB placement. */
  privateSubnetIds?: string[];

  /** List of public subnet IDs for the NLB. */
  publicSubnetIds?: string[];

  /** Custom domain name for the API Gateway (e.g. "api.Medyrax.example.com"). */
  apiDomainName?: string;

  /** ACM certificate ARN for the custom domain. */
  apiCertificateArn?: string;

  /**
   * Whether to enable AWS WAF on API Gateway.
   * Default: true for staging and prod; false for dev.
   */
  enableWaf?: boolean;

  /**
   * Whether to enable AWS HealthLake FHIR datastore provisioning.
   * HealthLake is slow to provision; disable in dev for fast iteration.
   * Default: false for dev; true for staging and prod.
   */
  enableHealthLake?: boolean;

  /**
   * Whether to enable MSK (Kafka) for analytics streaming.
   * Default: false for dev.
   */
  enableMsk?: boolean;

  /**
   * Whether to enable ElastiCache (Redis) for Terminology Service caching.
   * Default: false for dev (uses in-memory cache instead).
   */
  enableElastiCache?: boolean;

  /**
   * PagerDuty SNS topic ARN for critical alarms.
   * If undefined, alarms only route to CloudWatch.
   */
  pagerDutySnsTopicArn?: string;

  /**
   * S3 bucket name for the CDK asset staging bucket.
   * If undefined, CDK creates a default staging bucket.
   */
  cdkAssetBucketName?: string;

  /**
   * Whether to retain DynamoDB tables on stack deletion.
   * Default: true for staging and prod; false for dev (RETAIN would block teardown).
   */
  retainTables?: boolean;

  /**
   * Override for the default Cognito access token expiry in minutes.
   * Default: 15 (HIPAA requirement 7.7).
   */
  cognitoAccessTokenExpiryMinutes?: number;

  /**
   * Whether X-Ray active tracing is enabled on all Lambda functions.
   * Default: true for all environments.
   */
  enableXRay?: boolean;

  /**
   * MLLP listener port on the NLB (default 2575).
   */
  mllpPort?: number;
}
