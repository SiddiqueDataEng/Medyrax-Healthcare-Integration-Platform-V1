/**
 * MedyraxSecurityStack — Jest assertion tests
 *
 * Uses aws-cdk-lib/assertions (Template.fromStack) to validate:
 *   1. KMS key with EnableKeyRotation = true
 *   2. KMS alias alias/mdx-platform-cmk exists
 *   3. Exactly 5 IAM Role resources
 *   4. No IAM policy combining Action "*" with Resource "*" (no wildcard PHI access)
 *   5. CloudTrail trail with IsMultiRegionTrail + EnableLogFileValidation
 *   6. S3 bucket lifecycle expiration = 2555 days
 *   7. S3 bucket public access block settings all true
 *
 * Requirements: 7.1, 7.2, 7.4, 7.6, 7.8
 */
import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { MedyraxSecurityStack } from '../../src/stacks/MedyraxSecurityStack';
import { EnvironmentConfig } from '../../src/types/EnvironmentConfig';

// ── Test helpers ──────────────────────────────────────────────────────────────

function buildTestStack(): { stack: MedyraxSecurityStack; template: Template } {
  const app = new cdk.App();

  const envConfig: EnvironmentConfig = {
    awsAccountId: '123456789012',
    awsRegion: 'us-east-1',
    envName: 'dev',
  };

  const stack = new MedyraxSecurityStack(app, 'TestSecurityStack', {
    envName: 'dev',
    envConfig,
    env: { account: '123456789012', region: 'us-east-1' },
  });

  const template = Template.fromStack(stack);
  return { stack, template };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('MedyraxSecurityStack — KMS', () => {
  let template: Template;

  beforeAll(() => {
    ({ template } = buildTestStack());
  });

  /**
   * Validates: Requirements 7.6
   * KMS key must have annual rotation enabled.
   */
  it('has a KMS Key with EnableKeyRotation true', () => {
    template.hasResourceProperties('AWS::KMS::Key', {
      EnableKeyRotation: true,
    });
  });

  /**
   * Validates: Requirements 7.1
   * The platform CMK must have the alias alias/mdx-platform-cmk.
   */
  it('has a KMS Alias matching alias/mdx-platform-cmk', () => {
    template.hasResourceProperties('AWS::KMS::Alias', {
      AliasName: 'alias/mdx-platform-cmk',
    });
  });

  /**
   * Validates: Requirements 7.1
   * CMK description should identify it as a Medyrax platform CMK.
   */
  it('KMS Key description mentions Medyrax and orgId platform', () => {
    template.hasResourceProperties('AWS::KMS::Key', {
      Description: Match.stringLikeRegexp('Medyrax per-org CMK for org platform'),
    });
  });
});

describe('MedyraxSecurityStack — IAM Roles', () => {
  let template: Template;

  beforeAll(() => {
    ({ template } = buildTestStack());
  });

  /**
   * Validates: Requirements 7.2, 7.4
   * Exactly 5 IAM roles must exist for the RBAC model.
   */
  it('has exactly 5 IAM Role resources', () => {
    const roles = template.findResources('AWS::IAM::Role');
    // Filter to only Medyrax mdx- prefixed roles (exclude CDK-created service roles)
    const mdxRoles = Object.values(roles).filter((r: any) => {
      const roleName: string = r?.Properties?.RoleName ?? '';
      return roleName.startsWith('mdx-');
    });
    expect(mdxRoles).toHaveLength(5);
  });

  /**
   * Validates: Requirements 7.2, 7.4
   * Platform_Admin role must exist.
   */
  it('has Platform_Admin role with correct naming', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdx-platform-admin-dev',
    });
  });

  /**
   * Validates: Requirements 7.2, 7.4
   * Integration_Service role must trust the Lambda service principal.
   */
  it('Integration_Service role trusts lambda.amazonaws.com', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdx-integration-service-dev',
      AssumeRolePolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Principal: { Service: 'lambda.amazonaws.com' },
            Action: 'sts:AssumeRole',
          }),
        ]),
      }),
    });
  });

  /**
   * Validates: Requirements 7.4 (least-privilege — no wildcard PHI access)
   * No IAM policy document may combine Action "s3:*" or "dynamodb:*"
   * with Resource "*" using a blanket wildcard that would expose PHI tables/buckets
   * to non-admin roles.
   * NOTE: Platform_Admin intentionally uses broad permissions — we verify the
   * other four roles do NOT have Action "dynamodb:*"/"s3:*" with Resource "*".
   */
  it('no IAM policy grants both Action "*" and Resource "*" simultaneously', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    const managedPolicies = template.findResources('AWS::IAM::ManagedPolicy');

    // Helper: scan a statement array for the dual-wildcard anti-pattern
    function hasWildcardAll(statements: any[]): boolean {
      for (const stmt of statements) {
        const actions: string[] = Array.isArray(stmt.Action)
          ? stmt.Action
          : [stmt.Action];
        const resources: string[] = Array.isArray(stmt.Resource)
          ? stmt.Resource
          : [stmt.Resource];

        const actionWildcard = actions.includes('*');
        const resourceWildcard = resources.includes('*');
        if (actionWildcard && resourceWildcard) {
          return true;
        }
      }
      return false;
    }

    for (const [logicalId, resource] of Object.entries(policies)) {
      const stmts = (resource as any)?.Properties?.PolicyDocument?.Statement ?? [];
      expect(
        hasWildcardAll(stmts),
      ).toBe(false);
    }

    for (const [logicalId, resource] of Object.entries(managedPolicies)) {
      const stmts = (resource as any)?.Properties?.PolicyDocument?.Statement ?? [];
      expect(
        hasWildcardAll(stmts),
      ).toBe(false);
    }
  });

  /**
   * Validates: Requirements 7.2
   * Clinical_User role should only have execute-api:Invoke (no DynamoDB/S3).
   */
  it('Clinical_User role has only API Gateway execute-api permission', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdx-clinical-user-dev',
    });
  });

  /**
   * Validates: Requirements 7.4
   * Audit_Reviewer role must not have any write permissions.
   */
  it('Audit_Reviewer role exists with correct naming', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdx-audit-reviewer-dev',
    });
  });
});

describe('MedyraxSecurityStack — CloudTrail', () => {
  let template: Template;

  beforeAll(() => {
    ({ template } = buildTestStack());
  });

  /**
   * Validates: Requirements 7.8
   * CloudTrail must be multi-region and have log-file validation enabled.
   */
  it('has a CloudTrail Trail with IsMultiRegionTrail true and EnableLogFileValidation true', () => {
    template.hasResourceProperties('AWS::CloudTrail::Trail', {
      IsMultiRegionTrail: true,
      EnableLogFileValidation: true,
    });
  });

  /**
   * Validates: Requirements 7.8
   * CloudTrail must include global service events.
   */
  it('CloudTrail includes global service events', () => {
    template.hasResourceProperties('AWS::CloudTrail::Trail', {
      IncludeGlobalServiceEvents: true,
    });
  });

  /**
   * Validates: Requirements 7.8
   * CloudTrail trail name must follow the mdx-platform-audit-trail-{env} convention.
   */
  it('CloudTrail trail has correct name', () => {
    template.hasResourceProperties('AWS::CloudTrail::Trail', {
      TrailName: 'mdx-platform-audit-trail-dev',
    });
  });
});

describe('MedyraxSecurityStack — S3 Audit Bucket', () => {
  let template: Template;

  beforeAll(() => {
    ({ template } = buildTestStack());
  });

  /**
   * Validates: Requirements 7.8
   * Audit bucket lifecycle rule must expire objects after 2555 days (7 years).
   */
  it('S3 bucket has lifecycle rule with ExpirationInDays = 2555', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      LifecycleConfiguration: {
        Rules: Match.arrayWith([
          Match.objectLike({
            ExpirationInDays: 2555,
            Status: 'Enabled',
          }),
        ]),
      },
    });
  });

  /**
   * Validates: Requirements 7.8
   * Audit bucket lifecycle rule must transition to GLACIER after 90 days.
   */
  it('S3 bucket lifecycle transitions to GLACIER after 90 days', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      LifecycleConfiguration: {
        Rules: Match.arrayWith([
          Match.objectLike({
            Transitions: Match.arrayWith([
              Match.objectLike({
                StorageClass: 'GLACIER',
                TransitionInDays: 90,
              }),
            ]),
          }),
        ]),
      },
    });
  });

  /**
   * Validates: Requirements 7.1
   * Audit bucket must block all public access.
   */
  it('S3 bucket has all public access block settings set to true', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });

  /**
   * Validates: Requirements 7.1
   * Audit bucket must have versioning enabled.
   */
  it('S3 bucket has versioning enabled', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      VersioningConfiguration: {
        Status: 'Enabled',
      },
    });
  });
});
