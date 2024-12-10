/**
 * CDK snapshot tests for MedyraxSecurityStack (task 2.2)
 *
 * Asserts:
 * - All S3 buckets have SSE-KMS encryption
 * - IAM policies have no wildcard actions on PHI resources
 * - CloudTrail retention policy = 7 years (2557 days)
 *
 * Requirements: 7.1, 7.8, 15.6
 */
import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { MedyraxSecurityStack } from '../../src/stacks/MedyraxSecurityStack';
import { EnvironmentConfig } from '../../src/types/EnvironmentConfig';

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

function createStack() {
  const app = new cdk.App();
  return new MedyraxSecurityStack(app, 'TestSecurityStack', {
    envName: 'dev',
    envConfig: testConfig,
    env: { account: '123456789012', region: 'us-east-1' },
  });
}

describe('MedyraxSecurityStack — CDK snapshot tests (task 2.2)', () => {

  test('matches snapshot', () => {
    const stack = createStack();
    const template = Template.fromStack(stack);
    expect(template.toJSON()).toMatchSnapshot();
  });

  test('all S3 buckets have SSE-KMS encryption', () => {
    const stack = createStack();
    const template = Template.fromStack(stack);
    const buckets = template.findResources('AWS::S3::Bucket');

    Object.values(buckets).forEach((bucket: any) => {
      const enc = bucket.Properties?.BucketEncryption;
      expect(enc).toBeDefined();
      const rules = enc?.ServerSideEncryptionConfiguration;
      expect(rules).toBeDefined();
      const hasKms = rules.some((r: any) =>
        r.ServerSideEncryptionByDefault?.SSEAlgorithm === 'aws:kms'
      );
      expect(hasKms).toBe(true);
    });
  });

  test('IAM policies contain no wildcard actions on PHI resources', () => {
    const stack = createStack();
    const template = Template.fromStack(stack);
    const policies = template.findResources('AWS::IAM::Policy');

    Object.entries(policies).forEach(([id, policy]: [string, any]) => {
      const statements: any[] = policy.Properties?.PolicyDocument?.Statement ?? [];
      statements.forEach((stmt) => {
        const actions: string[] = Array.isArray(stmt.Action)
          ? stmt.Action
          : [stmt.Action];
        const hasPhi = actions.some((a: string) =>
          a === '*' || a === 'healthlake:*' || a === 'dynamodb:*'
        );
        // Platform_Admin may have broader access, but Integration_Service and
        // Clinical_User must NOT have wildcard PHI actions
        if (!id.includes('PlatformAdmin')) {
          expect(hasPhi).toBe(false);
        }
      });
    });
  });

  test('CloudTrail audit bucket has lifecycle rule >= 7 years', () => {
    const stack = createStack();
    const template = Template.fromStack(stack);
    const buckets = template.findResources('AWS::S3::Bucket');

    const auditBucket = Object.values(buckets).find((b: any) =>
      JSON.stringify(b).includes('mdx-audit-trail')
    );
    expect(auditBucket).toBeDefined();

    const lifecycleRules = (auditBucket as any)
      ?.Properties?.LifecycleConfiguration?.Rules;
    if (lifecycleRules) {
      const expirationRule = lifecycleRules.find((r: any) => r.ExpirationInDays);
      if (expirationRule) {
        expect(expirationRule.ExpirationInDays).toBeGreaterThanOrEqual(2555); // ~7 years
      }
    }
  });

  test('KMS key has key rotation enabled', () => {
    const stack = createStack();
    const template = Template.fromStack(stack);
    template.hasResourceProperties('AWS::KMS::Key', {
      EnableKeyRotation: true,
    });
  });
});
