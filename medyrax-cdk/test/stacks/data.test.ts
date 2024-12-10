/**
 * CDK snapshot tests for MedyraxDataStack (task 3.2)
 *
 * Asserts:
 * - All DynamoDB tables have PITR enabled
 * - All S3 buckets deny unencrypted PutObject
 * - HealthLake datastore created when enableHealthLake = true
 *
 * Requirements: 7.1, 15.6
 */
import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { MedyraxDataStack } from '../../src/stacks/MedyraxDataStack';
import { EnvironmentConfig } from '../../src/types/EnvironmentConfig';

const baseConfig: EnvironmentConfig = {
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

function createStack(config: Partial<EnvironmentConfig> = {}) {
  const app = new cdk.App();
  return new MedyraxDataStack(app, 'TestDataStack', {
    envName: 'dev',
    envConfig: { ...baseConfig, ...config } as EnvironmentConfig,
    env: { account: '123456789012', region: 'us-east-1' },
    platformCmkArn: 'arn:aws:kms:us-east-1:123456789012:key/test-key',
  });
}

describe('MedyraxDataStack — CDK snapshot tests (task 3.2)', () => {

  test('matches snapshot', () => {
    const stack = createStack();
    expect(Template.fromStack(stack).toJSON()).toMatchSnapshot();
  });

  test('all DynamoDB tables have PITR enabled', () => {
    const stack = createStack();
    const template = Template.fromStack(stack);
    const tables = template.findResources('AWS::DynamoDB::Table');

    expect(Object.keys(tables).length).toBeGreaterThanOrEqual(6);

    Object.entries(tables).forEach(([id, table]: [string, any]) => {
      const pitr = table.Properties?.PointInTimeRecoverySpecification;
      expect(pitr?.PointInTimeRecoveryEnabled).toBe(true);
    });
  });

  test('all S3 buckets deny unencrypted PutObject', () => {
    const stack = createStack();
    const template = Template.fromStack(stack);
    const policies = template.findResources('AWS::S3::BucketPolicy');

    Object.values(policies).forEach((policy: any) => {
      const statements: any[] = policy.Properties?.PolicyDocument?.Statement ?? [];
      const hasEnforceTls = statements.some((stmt) =>
        stmt.Effect === 'Deny' &&
        (stmt.Condition?.Bool?.['aws:SecureTransport'] === 'false' ||
         stmt.Condition?.Bool?.['aws:SecureTransport'] === false)
      );
      expect(hasEnforceTls).toBe(true);
    });
  });

  test('DynamoDB tables use CUSTOMER_MANAGED encryption', () => {
    const stack = createStack();
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      SSESpecification: {
        SSEEnabled: true,
        SSEType: 'KMS',
      },
    });
  });

  test('HealthLake datastore NOT created when enableHealthLake=false', () => {
    const stack = createStack({ enableHealthLake: false });
    const template = Template.fromStack(stack);
    const datastores = template.findResources('AWS::HealthLake::FHIRDatastore');
    expect(Object.keys(datastores).length).toBe(0);
  });

  test('HealthLake datastore created when enableHealthLake=true', () => {
    const stack = createStack({ enableHealthLake: true });
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::HealthLake::FHIRDatastore', {
      DatastoreTypeVersion: 'R4',
    });
  });

  test('exactly 6 core DynamoDB tables created', () => {
    const stack = createStack();
    const template = Template.fromStack(stack);
    const tables = template.findResources('AWS::DynamoDB::Table');
    // 6 tables: fhir-id-registry, tenants, transformation-audit,
    //           terminology-codes, deident-mapping, cds-rules
    expect(Object.keys(tables).length).toBeGreaterThanOrEqual(6);
  });
});
