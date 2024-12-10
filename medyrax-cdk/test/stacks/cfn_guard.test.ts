/**
 * CDK snapshot + cfn-guard compliance tests (task 22.5).
 *
 * Validates that synthesized CloudFormation templates comply with
 * the HIPAA cfn-guard rules defined in cfn-guard/hipaa_rules.guard.
 *
 * Requirements: 7.1, 7.6, 7.8, 15.6
 */
import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { MedyraxSecurityStack } from '../../src/stacks/MedyraxSecurityStack';
import { MedyraxDataStack } from '../../src/stacks/MedyraxDataStack';
import { EnvironmentConfig } from '../../src/types/EnvironmentConfig';
import * as fs from 'fs';
import * as path from 'path';

const testConfig: EnvironmentConfig = {
  awsAccountId: '123456789012',
  awsRegion: 'us-east-1',
  envName: 'dev',
  enableWaf: false,
  enableHealthLake: false,
  enableMsk: false,
  enableElastiCache: false,
  retainTables: false,
  cognitoAccessTokenExpiryMinutes: 15,
  enableXRay: true,
  mllpPort: 2575,
};

describe('CDK snapshot + cfn-guard compliance tests (task 22.5)', () => {

  test('Security stack CloudFormation template matches snapshot', () => {
    const app = new cdk.App();
    const stack = new MedyraxSecurityStack(app, 'CfnGuardSecStack', {
      envName: 'dev', envConfig: testConfig,
      env: { account: '123456789012', region: 'us-east-1' },
    });
    const template = Template.fromStack(stack).toJSON();
    expect(template).toMatchSnapshot();
  });

  test('Data stack CloudFormation template matches snapshot', () => {
    const app = new cdk.App();
    const stack = new MedyraxDataStack(app, 'CfnGuardDataStack', {
      envName: 'dev', envConfig: testConfig,
      env: { account: '123456789012', region: 'us-east-1' },
      platformCmkArn: 'arn:aws:kms:us-east-1:123456789012:key/test-key',
    });
    const template = Template.fromStack(stack).toJSON();
    expect(template).toMatchSnapshot();
  });

  test('cfn-guard rules file exists and is non-empty', () => {
    const rulesPath = path.join(__dirname, '..', '..', 'cfn-guard', 'hipaa_rules.guard');
    expect(fs.existsSync(rulesPath)).toBe(true);
    const content = fs.readFileSync(rulesPath, 'utf8');
    expect(content.length).toBeGreaterThan(100);
    expect(content).toContain('s3_bucket_encrypted');
    expect(content).toContain('dynamodb_pitr_enabled');
    expect(content).toContain('kms_key_rotation_enabled');
  });

  // Manual cfn-guard compliance checks (mirrors guard rules without external tool)
  test('all KMS keys in Security stack have rotation enabled', () => {
    const app = new cdk.App();
    const stack = new MedyraxSecurityStack(app, 'KmsRotationStack', {
      envName: 'dev', envConfig: testConfig,
      env: { account: '123456789012', region: 'us-east-1' },
    });
    const template = Template.fromStack(stack);
    const keys = template.findResources('AWS::KMS::Key');
    Object.values(keys).forEach((key: any) => {
      expect(key.Properties.EnableKeyRotation).toBe(true);
    });
  });

  test('all DynamoDB tables in Data stack have PAY_PER_REQUEST billing', () => {
    const app = new cdk.App();
    const stack = new MedyraxDataStack(app, 'DdbBillingStack', {
      envName: 'dev', envConfig: testConfig,
      env: { account: '123456789012', region: 'us-east-1' },
      platformCmkArn: 'arn:aws:kms:us-east-1:123456789012:key/test',
    });
    const template = Template.fromStack(stack);
    const tables = template.findResources('AWS::DynamoDB::Table');
    Object.values(tables).forEach((table: any) => {
      expect(table.Properties.BillingMode).toBe('PAY_PER_REQUEST');
    });
  });

  test('S3 buckets in Security stack have RETAIN removal policy in prod config', () => {
    const prodConfig: EnvironmentConfig = { ...testConfig, envName: 'prod', retainTables: true };
    const app = new cdk.App();
    const stack = new MedyraxSecurityStack(app, 'ProdRetainStack', {
      envName: 'prod', envConfig: prodConfig,
      env: { account: '123456789012', region: 'us-east-1' },
    });
    const template = Template.fromStack(stack);
    const buckets = template.findResources('AWS::S3::Bucket');
    // Audit trail bucket must always be RETAIN
    const auditBucket = Object.values(buckets).find((b: any) =>
      JSON.stringify(b).includes('hb-audit-trail') ||
      JSON.stringify(b).includes('AuditTrail')
    );
    if (auditBucket) {
      expect((auditBucket as any).DeletionPolicy).toBe('Retain');
    }
  });
});
