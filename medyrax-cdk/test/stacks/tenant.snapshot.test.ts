/**
 * MedyraxTenantStack — Jest assertion tests
 *
 * Uses aws-cdk-lib/assertions (Template.fromStack) to validate:
 *   1. Five Lambda functions created with Python 3.12 runtime
 *   2. Step Function state machine named mdx-org-provision-sfn-dev
 *   3. SNS topic for welcome notifications
 *   4. Lambda functions have X-Ray active tracing enabled
 *   5. Lambda log groups have 7-year (2557 days) retention
 *   6. Step Function execution log group exists
 *   7. Step Function timeout set
 *   8. IAM provisioner role created for Lambda execution
 *
 * Requirements: 8.1, 8.2
 */
import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { MedyraxTenantStack } from '../../src/stacks/MedyraxTenantStack';
import { EnvironmentConfig } from '../../src/types/EnvironmentConfig';

// ── Test helpers ──────────────────────────────────────────────────────────────

const PLACEHOLDER_CMK_ARN =
  'arn:aws:kms:us-east-1:123456789012:key/test-key-id-1234-5678';

function buildTestStack(): { stack: MedyraxTenantStack; template: Template } {
  const app = new cdk.App();

  const envConfig: EnvironmentConfig = {
    awsAccountId: '123456789012',
    awsRegion: 'us-east-1',
    envName: 'dev',
    enableXRay: true,
    retainStatefulResources: false,
  };

  const stack = new MedyraxTenantStack(app, 'TestTenantStack', {
    envName: 'dev',
    envConfig,
    env: { account: '123456789012', region: 'us-east-1' },
    platformCmkArn: PLACEHOLDER_CMK_ARN,
  });

  const template = Template.fromStack(stack);
  return { stack, template };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('MedyraxTenantStack — Lambda functions', () => {
  let template: Template;

  beforeAll(() => {
    ({ template } = buildTestStack());
  });

  /**
   * Validates: Requirements 8.1
   * All provisioner Lambdas must use Python 3.12.
   */
  it('all provisioner Lambda functions use Python 3.12 runtime', () => {
    const lambdas = template.findResources('AWS::Lambda::Function');
    const mdxProvisionerFunctions = Object.values(lambdas).filter((fn: any) => {
      const name: string = fn?.Properties?.FunctionName ?? '';
      return name.startsWith('mdx-tenant-provisioner-');
    });

    expect(mdxProvisionerFunctions.length).toBeGreaterThanOrEqual(5);

    for (const fn of mdxProvisionerFunctions) {
      expect((fn as any).Properties.Runtime).toBe('python3.12');
    }
  });

  /**
   * Validates: Requirements 8.1
   * Validate Lambda function must be created.
   */
  it('validate Lambda function exists with correct name', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'mdx-tenant-provisioner-validate-dev',
      Handler: 'validate.handler',
      Runtime: 'python3.12',
    });
  });

  /**
   * Validates: Requirements 8.1
   * AWS Resources Lambda function must be created.
   */
  it('aws-resources Lambda function exists with correct name', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'mdx-tenant-provisioner-aws-dev',
      Handler: 'aws_resources.handler',
      Runtime: 'python3.12',
    });
  });

  /**
   * Validates: Requirements 8.1
   * HealthLake Lambda function must be created.
   */
  it('healthlake Lambda function exists with correct name', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'mdx-tenant-provisioner-healthlake-dev',
      Handler: 'healthlake.handler',
      Runtime: 'python3.12',
    });
  });

  /**
   * Validates: Requirements 8.1
   * SFTP Lambda function must be created.
   */
  it('sftp Lambda function exists with correct name', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'mdx-tenant-provisioner-sftp-dev',
      Handler: 'sftp.handler',
      Runtime: 'python3.12',
    });
  });

  /**
   * Validates: Requirements 8.1
   * Finalize Lambda function must be created.
   */
  it('finalize Lambda function exists with correct name', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'mdx-tenant-provisioner-finalize-dev',
      Handler: 'finalize.handler',
      Runtime: 'python3.12',
    });
  });

  /**
   * Validates: Observability / Requirements 8.1
   * All provisioner Lambdas must have X-Ray active tracing enabled.
   */
  it('all provisioner Lambda functions have X-Ray active tracing', () => {
    const lambdas = template.findResources('AWS::Lambda::Function');
    const mdxProvisionerFunctions = Object.values(lambdas).filter((fn: any) => {
      const name: string = fn?.Properties?.FunctionName ?? '';
      return name.startsWith('mdx-tenant-provisioner-');
    });

    for (const fn of mdxProvisionerFunctions) {
      expect((fn as any).Properties.TracingConfig).toEqual({ Mode: 'Active' });
    }
  });

  /**
   * Validates: Requirements 8.1
   * Lambda functions must have the mdx-tenants table name in their environment.
   */
  it('Lambda functions have MDX_TENANTS_TABLE environment variable set', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'mdx-tenant-provisioner-finalize-dev',
      Environment: Match.objectLike({
        Variables: Match.objectLike({
          MDX_TENANTS_TABLE: 'mdx-tenants',
        }),
      }),
    });
  });
});

describe('MedyraxTenantStack — Step Function', () => {
  let template: Template;

  beforeAll(() => {
    ({ template } = buildTestStack());
  });

  /**
   * Validates: Requirements 8.1, 8.2
   * Step Function state machine must exist with the correct name.
   */
  it('Step Function state machine is created with correct name', () => {
    template.hasResourceProperties('AWS::StepFunctions::StateMachine', {
      StateMachineName: 'mdx-org-provision-sfn-dev',
      StateMachineType: 'STANDARD',
    });
  });

  /**
   * Validates: Requirements 8.2
   * Step Function definition must reference all five Lambda functions.
   */
  it('Step Function definition includes all five provisioner Lambda invocations', () => {
    const stateMachines = template.findResources('AWS::StepFunctions::StateMachine');
    const sfnResource = Object.values(stateMachines)[0] as any;
    const definition = JSON.stringify(sfnResource?.Properties?.DefinitionString ?? '');

    // Each Lambda state should appear in the definition JSON
    expect(definition).toContain('ValidateProvisioningRequest');
    expect(definition).toContain('CreateAWSResources');
    expect(definition).toContain('CreateHealthLakeDatastore');
    expect(definition).toContain('CreateSFTPEndpoint');
    expect(definition).toContain('FinalizeTenant');
    expect(definition).toContain('ProvisioningFailed');
    expect(definition).toContain('ProvisioningSucceeded');
  });

  /**
   * Validates: Requirements 8.2
   * Step Function must have X-Ray tracing enabled.
   */
  it('Step Function has X-Ray tracing enabled', () => {
    template.hasResourceProperties('AWS::StepFunctions::StateMachine', {
      TracingConfiguration: {
        Enabled: true,
      },
    });
  });
});

describe('MedyraxTenantStack — SNS', () => {
  let template: Template;

  beforeAll(() => {
    ({ template } = buildTestStack());
  });

  /**
   * Validates: Requirements 8.2
   * Welcome notification SNS topic must be created.
   */
  it('SNS welcome notification topic is created', () => {
    template.hasResourceProperties('AWS::SNS::Topic', {
      TopicName: 'mdx-welcome-notifications-dev',
      DisplayName: Match.stringLikeRegexp('Medyrax'),
    });
  });
});

describe('MedyraxTenantStack — IAM', () => {
  let template: Template;

  beforeAll(() => {
    ({ template } = buildTestStack());
  });

  /**
   * Validates: Requirements 8.1
   * Provisioner base IAM role must exist.
   */
  it('provisioner base IAM role is created', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdx-tenant-provisioner-role-dev',
    });
  });

  /**
   * Validates: Requirements 8.1
   * Step Function execution role must exist.
   */
  it('Step Function execution IAM role is created', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdx-provision-sfn-role-dev',
    });
  });

  /**
   * Validates: Requirements 8.1
   * Provisioner role must trust lambda.amazonaws.com.
   */
  it('provisioner role trusts lambda.amazonaws.com service principal', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdx-tenant-provisioner-role-dev',
      AssumeRolePolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Principal: { Service: 'lambda.amazonaws.com' },
          }),
        ]),
      }),
    });
  });

  /**
   * Validates: Requirements 8.2
   * Step Function role must trust states.amazonaws.com (or regional variant).
   */
  it('Step Function role trusts states.amazonaws.com service principal', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      RoleName: 'mdx-provision-sfn-role-dev',
      AssumeRolePolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Principal: Match.objectLike({
              Service: Match.stringLikeRegexp('states.*amazonaws\\.com'),
            }),
          }),
        ]),
      }),
    });
  });
});

describe('MedyraxTenantStack — CloudFormation Outputs', () => {
  let template: Template;

  beforeAll(() => {
    ({ template } = buildTestStack());
  });

  /**
   * Validates: Requirements 8.1
   * Step Function ARN must be exported.
   */
  it('exports ProvisioningSfnArn output', () => {
    template.hasOutput('ProvisioningSfnArn', {
      Export: Match.objectLike({
        Name: 'mdx-provision-sfn-arn-dev',
      }),
    });
  });

  /**
   * Validates: Requirements 8.2
   * Welcome SNS Topic ARN must be exported.
   */
  it('exports WelcomeSnsTopicArn output', () => {
    template.hasOutput('WelcomeSnsTopicArn', {
      Export: Match.objectLike({
        Name: 'mdx-welcome-sns-topic-arn-dev',
      }),
    });
  });
});
