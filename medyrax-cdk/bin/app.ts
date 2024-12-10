#!/usr/bin/env node
/**
 * Medyrax™ CDK App Entry Point
 *
 * Reads the --context env=<dev|staging|prod> flag from the CDK CLI, loads the
 * corresponding config/{env}.json file as an {@link EnvironmentConfig}, and
 * instantiates stub CDK stacks for each platform layer.
 *
 * Usage:
 *   cdk synth --context env=dev
 *   cdk deploy --context env=staging --all
 *   cdk deploy --context env=prod --all --require-approval any
 */
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import * as fs from 'fs';
import { EnvironmentConfig } from '../src/types/EnvironmentConfig';
import { MedyraxSecurityStack } from '../src/stacks/MedyraxSecurityStack';
import { MedyraxDataStack } from '../src/stacks/MedyraxDataStack';
import { MedyraxTenantStack } from '../src/stacks/MedyraxTenantStack';
import { MedyraxCoreStack } from '../src/stacks/MedyraxCoreStack';
import { MedyraxObsStack } from '../src/stacks/MedyraxObsStack';

const app = new cdk.App();

// ── Resolve environment name from CDK context ─────────────────────────────
const envName: string = app.node.tryGetContext('env') ?? 'dev';

// ── Load environment configuration from config/{env}.json ─────────────────
const configPath = path.join(__dirname, '..', 'config', `${envName}.json`);

if (!fs.existsSync(configPath)) {
  throw new Error(
    `Environment config not found at ${configPath}. ` +
    `Pass --context env=<dev|staging|prod> to the CDK CLI.`
  );
}

const envConfig: EnvironmentConfig = JSON.parse(fs.readFileSync(configPath, 'utf8'));

// ── Build the CDK environment descriptor ──────────────────────────────────
const stackEnv: cdk.Environment = {
  account: envConfig.awsAccountId,
  region: envConfig.awsRegion,
};

// ── Common props forwarded to every stack ─────────────────────────────────
const stackProps = { envName, envConfig, env: stackEnv };

// ── Instantiate platform stacks ───────────────────────────────────────────
// Each stack is a stub (plain cdk.Stack) for now.  Task 2 onwards replaces
// these with typed stack classes that contain real CDK constructs.

/** Security Stack — KMS CMKs, IAM RBAC roles, CloudTrail (Task 2). */
new MedyraxSecurityStack(app, `MedyraxSecurityStack-${envName}`, {
  ...stackProps,
  stackName: `medyrax-security-${envName}`,
  description: 'Medyrax™ Security Layer: KMS, IAM RBAC, CloudTrail audit trail',
});

/** Data Stack — DynamoDB tables, S3 buckets, HealthLake (Task 3). */
new MedyraxDataStack(app, `MedyraxDataStack-${envName}`, {
  ...stackProps,
  stackName: `medyrax-data-${envName}`,
  description: 'Medyrax™ Data Layer: DynamoDB, S3, HealthLake FHIR datastore',
  // Forward the platform CMK ARN from the Security Stack export.
  // The Fn::ImportValue token is resolved at deploy time by CloudFormation.
  platformCmkArn: cdk.Fn.importValue(`mdx-platform-cmk-arn-${envName}`),
});

/** Core Stack — API Gateway, Cognito User Pool, base routes (Tasks 5.4, 9.5, 13.5, 14.1–14.4). */
const coreStack = new MedyraxCoreStack(app, `MedyraxCoreStack-${envName}`, {
  ...stackProps,
  stackName: `medyrax-core-${envName}`,
  description: 'Medyrax™ Core Layer: API Gateway, Cognito, base routes',
});

/** Observability Stack — CloudWatch alarms, dashboards, X-Ray (Tasks 21.1–21.6). */
const obsStack = new MedyraxObsStack(app, `MedyraxObsStack-${envName}`, {
  ...stackProps,
  stackName: `medyrax-obs-${envName}`,
  description: 'Medyrax™ Observability Layer: CloudWatch, X-Ray, PagerDuty alarms',
});
obsStack.addDependency(coreStack);

/** Tenant Stack — per-org provisioning CDK constructs (Task 4). */
new MedyraxTenantStack(app, `MedyraxTenantStack-${envName}`, {
  ...stackProps,
  stackName: `medyrax-tenant-${envName}`,
  description: 'Medyrax™ Tenant Layer: multi-org provisioning Step Function and Lambdas',
  // Forward the platform CMK ARN from the Security Stack CloudFormation export.
  platformCmkArn: cdk.Fn.importValue(`mdx-platform-cmk-arn-${envName}`),
  // Forward the platform data bucket ARN from the Data Stack export.
  platformDataBucketArn: `arn:aws:s3:::mdx-platform-data-${envName}-${envConfig.awsAccountId}`,
});

app.synth();
