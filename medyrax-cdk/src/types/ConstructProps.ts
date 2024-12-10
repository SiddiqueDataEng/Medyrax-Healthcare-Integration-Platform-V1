/**
 * Shared CDK construct prop interfaces for Medyrax™ platform.
 *
 * Used across all CDK stacks and constructs. Extends cdk.StackProps
 * with environment-specific configuration.
 *
 * Requirements: 1.1, 2.1, 5.1, 13.1
 */
import * as cdk from 'aws-cdk-lib';
import { EnvironmentConfig } from './EnvironmentConfig';

/** Base props shared by all Medyrax CDK stacks. */
export interface MedyraxStackProps extends cdk.StackProps {
  envName: string;
  envConfig: EnvironmentConfig;
}

/** Props for HipaaCompliantBucket construct. */
export interface HipaaCompliantBucketProps {
  bucketNamePrefix: string;
  kmsKeyArn: string;
  versioned?: boolean;
  archiveAfterDays?: number;
  serverAccessLogsBucketArn?: string;
  removalPolicy?: cdk.RemovalPolicy;
}

/** Props for TenantIsolatedQueue construct (SQS FIFO + per-org KMS). */
export interface TenantIsolatedQueueProps {
  orgId: string;
  queueNameSuffix: string;
  kmsKeyArn: string;
  fifo?: boolean;
  visibilityTimeoutSeconds?: number;
  maxReceiveCount?: number;
}

/** Props for HipaaKmsConstruct (per-org CMK with 365-day auto-rotation). */
export interface HipaaKmsConstructProps {
  orgId: string;
  accountId: string;
  rotationDays?: number;
  grantedRoleArns?: string[];
}

/** Props for HipaaIamRoles construct. */
export interface HipaaIamRolesProps {
  envName: string;
  accountId: string;
  kmsKeyArn: string;
}

/** Props for HipaaAuditTrail construct. */
export interface HipaaAuditTrailProps {
  envName: string;
  kmsKeyArn?: string;
}
