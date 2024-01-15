#!/usr/bin/env node
/**
 * Medyrax™ Platform — CDK Application Entry Point
 *
 * Selects the target environment from --context env=<dev|staging|prod>
 * and instantiates all platform stacks. Stack dependencies are expressed
 * via CDK cross-stack references so that CloudFormation can determine
 * the correct deployment order.
 *
 * Usage:
 *   cdk synth --context env=dev
 *   cdk deploy --context env=staging --all
 */

import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import * as fs from 'fs';

import { MedyraxSecurityStack } from '../lib/stacks/MedyraxSecurityStack';
import { MedyraxDataStack } from '../lib/stacks/MedyraxDataStack';
import { MedyraxCoreStack } from '../lib/stacks/MedyraxCoreStack';
import { MedyraxObsStack } from '../lib/stacks/MedyraxObsStack';
import { MedyraxTenantStack } from '../lib/stacks/MedyraxTenantStack';
import { EnvironmentConfig } from '../lib/types';

// ── Environment selection ────────────────────────────────────────────────────

const app = new cdk.App();

const envName = app.node.tryGetContext('env') ?? 'dev';
const configPath = path.join(__dirname, '..', 'config', `${envName}.json`);

if (!fs.existsSync(configPath)) {
  throw new Error(
    `Environment config not found at ${configPath}. ` +
    `Valid values: dev, staging, prod. Use --context env=<name>.`
  );
}

const envConfig: EnvironmentConfig = JSON.parse(fs.readFileSync(configPath, 'utf-8'));

const awsEnv: cdk.Environment = {
  account: envConfig.awsAccountId ?? process.env.CDK_DEFAULT_ACCOUNT,
  region:  envConfig.awsRegion   ?? process.env.CDK_DEFAULT_REGION,
};

const commonProps: cdk.StackProps = {
  env: awsEnv,
  tags: {
    Project:     'Medyrax',
    Environment: envName,
    ManagedBy:   'CDK',
    Compliance:  'HIPAA',
  },
};

// ── Stack instantiation (dependency order matters) ───────────────────────────

/**
 * 1. Security Stack — KMS CMKs, IAM roles, CloudTrail.
 *    No dependencies. Must be deployed first.
 */
const securityStack = new MedyraxSecurityStack(app, `MDX-Security-${envName}`, {
  ...commonProps,
  envName,
  envConfig,
});

/**
 * 2. Data Stack — S3 buckets, DynamoDB tables, HealthLake placeholder.
 *    Depends on Security Stack for KMS key ARNs.
 */
const dataStack = new MedyraxDataStack(app, `MDX-Data-${envName}`, {
  ...commonProps,
  envName,
  envConfig,
  platformAdminKeyArn: securityStack.platformAdminKeyArn,
});
dataStack.addDependency(securityStack);

/**
 * 3. Core Stack — API Gateway, Lambda functions, EventBridge, SQS.
 *    Depends on Security and Data stacks.
 */
const coreStack = new MedyraxCoreStack(app, `MDX-Core-${envName}`, {
  ...commonProps,
  envName,
  envConfig,
  securityStack,
  dataStack,
});
coreStack.addDependency(securityStack);
coreStack.addDependency(dataStack);

/**
 * 4. Observability Stack — CloudWatch alarms, dashboards, X-Ray groups.
 *    Depends on Core Stack for Lambda ARNs and queue names.
 */
const obsStack = new MedyraxObsStack(app, `MDX-Obs-${envName}`, {
  ...commonProps,
  envName,
  envConfig,
  coreStack,
});
obsStack.addDependency(coreStack);

/**
 * 5. Tenant Stack — per-org provisioning CDK constructs (instantiated
 *    dynamically during the provisioning Step Function; this stack defines
 *    the reusable constructs and the provisioning Step Function itself).
 */
const tenantStack = new MedyraxTenantStack(app, `MDX-Tenant-${envName}`, {
  ...commonProps,
  envName,
  envConfig,
  securityStack,
  dataStack,
});
tenantStack.addDependency(dataStack);
tenantStack.addDependency(securityStack);

app.synth();
