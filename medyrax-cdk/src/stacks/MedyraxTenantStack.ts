/**
 * MedyraxTenantStack
 *
 * CDK Stack that provisions the multi-tenant management subsystem:
 *
 *   1. Five Lambda functions (tenant-provisioner-*) for the provisioning workflow
 *   2. Step Function state machine ``mdx-org-provision-sfn`` wiring all five
 *      Lambda states (Requirements 8.1, 8.2)
 *   3. SNS welcome notification topic
 *   4. IAM roles and policies for the Step Function and Lambda functions
 *
 * Provisioning Step Function states:
 *   ValidateProvisioningRequest → CreateAWSResources → CreateHealthLakeDatastore
 *   → CreateSFTPEndpoint → FinalizeTenant → (success | ProvisioningFailed)
 *
 * Lambda source: ``../../lambdas/tenant-provisioner/``
 * Python 3.12, X-Ray active tracing enabled.
 *
 * Requirements: 8.1, 8.2
 */
import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as path from 'path';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '@mdx/types';

// ── Stack-specific props ──────────────────────────────────────────────────────

export interface MedyraxTenantStackProps extends MedyraxStackProps {
  /**
   * ARN of the platform-level KMS CMK from MedyraxSecurityStack.
   * Used to encrypt Lambda environment variables and SNS messages.
   */
  platformCmkArn: string;

  /**
   * Name of the DynamoDB table where tenant config records are written.
   * Defaults to 'mdx-tenants'.
   */
  tenantsTableName?: string;

  /**
   * ARN of the platform data S3 bucket (created by MedyraxDataStack).
   * Lambda functions need s3:PutObject on this bucket to create per-org prefixes.
   */
  platformDataBucketArn?: string;

  /**
   * Pre-existing AWS Transfer Family server ID to reuse for SFTP user creation.
   * When omitted, the sftp Lambda creates a new server on first invocation.
   */
  transferServerid?: string;
}

// ── Stack ─────────────────────────────────────────────────────────────────────

export class MedyraxTenantStack extends cdk.Stack {
  /** Step Function state machine: mdx-org-provision-sfn */
  public readonly provisioningSfn: sfn.StateMachine;
  /** SNS topic for welcome notifications */
  public readonly welcomeSnsTopic: sns.Topic;
  /** Lambda: tenant-provisioner-validate */
  public readonly validateLambda: lambda.Function;
  /** Lambda: tenant-provisioner-aws */
  public readonly awsResourcesLambda: lambda.Function;
  /** Lambda: tenant-provisioner-healthlake */
  public readonly healthlakeLambda: lambda.Function;
  /** Lambda: tenant-provisioner-sftp */
  public readonly sftpLambda: lambda.Function;
  /** Lambda: tenant-provisioner-finalize */
  public readonly finalizeLambda: lambda.Function;

  constructor(scope: Construct, id: string, props: MedyraxTenantStackProps) {
    super(scope, id, props);

    const {
      envName,
      envConfig,
      platformCmkArn,
      tenantsTableName = 'mdx-tenants',
      platformDataBucketArn,
      transferServerid,
    } = props;

    // ── Resolve platform CMK ──────────────────────────────────────────────
    const platformCmk = kms.Key.fromKeyArn(this, 'PlatformCmk', platformCmkArn);

    // ── Determine removal / retention policy ──────────────────────────────
    const removalPolicy = envConfig.retainStatefulResources
      ? cdk.RemovalPolicy.RETAIN
      : cdk.RemovalPolicy.DESTROY;

    // ─────────────────────────────────────────────────────────────────────
    // 1. WELCOME SNS TOPIC
    // ─────────────────────────────────────────────────────────────────────
    this.welcomeSnsTopic = new sns.Topic(this, 'WelcomeNotificationTopic', {
      topicName: `mdx-welcome-notifications-${envName}`,
      displayName: 'Medyrax™ Platform — Tenant Provisioning Notifications',
      masterKey: platformCmk,
    });

    // ─────────────────────────────────────────────────────────────────────
    // 2. SHARED LAMBDA EXECUTION ROLE
    //    All provisioning Lambdas use this base role; individual Lambdas
    //    receive additional inline policies below.
    // ─────────────────────────────────────────────────────────────────────
    const provisionerBaseRole = new iam.Role(this, 'ProvisionerBaseRole', {
      roleName: `mdx-tenant-provisioner-role-${envName}`,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          'service-role/AWSLambdaBasicExecutionRole',
        ),
      ],
      description: 'Execution role shared by all tenant-provisioner Lambdas',
    });

    // Grant KMS CMK usage (encrypt Lambda env vars + SNS)
    platformCmk.grantEncryptDecrypt(provisionerBaseRole);

    // Grant DynamoDB access to mdx-tenants table
    provisionerBaseRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'TenantsTableAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'dynamodb:GetItem',
          'dynamodb:PutItem',
          'dynamodb:UpdateItem',
          'dynamodb:DeleteItem',
          'dynamodb:Query',
          'dynamodb:Scan',
        ],
        resources: [
          `arn:aws:dynamodb:${this.region}:${this.account}:table/${tenantsTableName}`,
          `arn:aws:dynamodb:${this.region}:${this.account}:table/${tenantsTableName}/index/*`,
        ],
      }),
    );

    // Grant KMS key administration for creating per-org CMKs
    provisionerBaseRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'KmsKeyManagement',
        effect: iam.Effect.ALLOW,
        actions: [
          'kms:CreateKey',
          'kms:CreateAlias',
          'kms:DescribeKey',
          'kms:EnableKeyRotation',
          'kms:TagResource',
          'kms:ListAliases',
        ],
        resources: ['*'],
      }),
    );

    // Grant IAM role management for creating per-org execution roles
    provisionerBaseRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'IamRoleManagement',
        effect: iam.Effect.ALLOW,
        actions: [
          'iam:CreateRole',
          'iam:GetRole',
          'iam:PutRolePolicy',
          'iam:AttachRolePolicy',
          'iam:TagRole',
          'iam:PassRole',
        ],
        resources: [
          `arn:aws:iam::${this.account}:role/mdx-*-execution-role`,
        ],
      }),
    );

    // Grant SQS queue creation
    provisionerBaseRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'SqsQueueManagement',
        effect: iam.Effect.ALLOW,
        actions: [
          'sqs:CreateQueue',
          'sqs:GetQueueUrl',
          'sqs:GetQueueAttributes',
          'sqs:SetQueueAttributes',
          'sqs:TagQueue',
        ],
        resources: [
          `arn:aws:sqs:${this.region}:${this.account}:mdx-*`,
        ],
      }),
    );

    // Grant EventBridge custom bus creation
    provisionerBaseRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'EventBridgeBusManagement',
        effect: iam.Effect.ALLOW,
        actions: [
          'events:CreateEventBus',
          'events:DescribeEventBus',
          'events:PutRule',
          'events:TagResource',
        ],
        resources: [
          `arn:aws:events:${this.region}:${this.account}:event-bus/mdx-*`,
        ],
      }),
    );

    // Grant S3 prefix creation on platform data bucket (optional)
    if (platformDataBucketArn) {
      provisionerBaseRole.addToPolicy(
        new iam.PolicyStatement({
          sid: 'S3PrefixCreation',
          effect: iam.Effect.ALLOW,
          actions: ['s3:PutObject', 's3:GetObject'],
          resources: [`${platformDataBucketArn}/*`],
        }),
      );
    }

    // Grant SNS publish for welcome notifications
    provisionerBaseRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'SnsWelcomePublish',
        effect: iam.Effect.ALLOW,
        actions: ['sns:Publish'],
        resources: [this.welcomeSnsTopic.topicArn],
      }),
    );

    // Grant AWS HealthLake datastore management
    provisionerBaseRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'HealthLakeManagement',
        effect: iam.Effect.ALLOW,
        actions: [
          'healthlake:CreateFHIRDatastore',
          'healthlake:DescribeFHIRDatastore',
          'healthlake:ListFHIRDatastores',
          'healthlake:TagResource',
        ],
        resources: ['*'],
      }),
    );

    // Grant AWS Transfer Family server/user management
    provisionerBaseRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'TransferFamilyManagement',
        effect: iam.Effect.ALLOW,
        actions: [
          'transfer:CreateServer',
          'transfer:DescribeServer',
          'transfer:CreateUser',
          'transfer:DescribeUser',
          'transfer:TagResource',
        ],
        resources: ['*'],
      }),
    );

    // ─────────────────────────────────────────────────────────────────────
    // 3. LAMBDA ASSET PATH
    //    All tenant-provisioner Lambdas are loaded from the same directory.
    //    Resolve the CDK project root by walking up from __dirname until we
    //    find a directory containing cdk.json.  This works whether we are
    //    running from src/stacks/ (ts-jest) or dist/src/stacks/ (compiled).
    // ─────────────────────────────────────────────────────────────────────
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const fs = require('fs') as typeof import('fs');

    function findCdkRoot(startDir: string): string {
      let dir = startDir;
      for (let i = 0; i < 6; i++) {
        if (fs.existsSync(path.join(dir, 'cdk.json'))) {
          return dir;
        }
        dir = path.dirname(dir);
      }
      // Fallback: assume two levels above src/stacks
      return path.join(startDir, '..', '..');
    }

    const cdkProjectRoot = findCdkRoot(__dirname);
    const lambdaAssetPath = path.join(
      cdkProjectRoot,
      '..',
      'lambdas',
      'tenant-provisioner',
    );

    // Shared Lambda props
    const commonLambdaProps: Partial<lambda.FunctionProps> = {
      runtime: lambda.Runtime.PYTHON_3_12,
      role: provisionerBaseRole,
      tracing: envConfig.enableXRay ? lambda.Tracing.ACTIVE : lambda.Tracing.DISABLED,
      memorySize: 512,
      timeout: cdk.Duration.minutes(15),  // max for HealthLake polling
      environmentEncryption: platformCmk,
      environment: {
        MDX_TENANTS_TABLE: tenantsTableName,
        MDX_WELCOME_SNS_TOPIC_ARN: this.welcomeSnsTopic.topicArn,
        AWS_ACCOUNT_ID: this.account,
        ...(platformDataBucketArn
          ? { MDX_PLATFORM_DATA_BUCKET: `mdx-platform-data-${envName}-${this.account}` }
          : {}),
        ...(transferServerid
          ? { MDX_TRANSFER_SERVER_ID: transferServerid }
          : {}),
      },
    };

    // CloudWatch log groups for each Lambda (explicit to set retention)
    const logRetention = logs.RetentionDays.SEVEN_YEARS; // HIPAA

    // ─────────────────────────────────────────────────────────────────────
    // 3a. VALIDATE LAMBDA
    // ─────────────────────────────────────────────────────────────────────
    const validateLogGroup = new logs.LogGroup(this, 'ValidateLogGroup', {
      logGroupName: `/aws/lambda/mdx-tenant-provisioner-validate-${envName}`,
      retention: logRetention,
      removalPolicy,
      encryptionKey: platformCmk,
    });

    this.validateLambda = new lambda.Function(this, 'ValidateLambda', {
      ...commonLambdaProps,
      functionName: `mdx-tenant-provisioner-validate-${envName}`,
      description: 'Step 1: Validate provisioning request schema',
      code: lambda.Code.fromAsset(lambdaAssetPath),
      handler: 'validate.handler',
      timeout: cdk.Duration.seconds(30),  // validation is fast
      logGroup: validateLogGroup,
    } as lambda.FunctionProps);

    // ─────────────────────────────────────────────────────────────────────
    // 3b. AWS RESOURCES LAMBDA
    // ─────────────────────────────────────────────────────────────────────
    const awsResourcesLogGroup = new logs.LogGroup(this, 'AwsResourcesLogGroup', {
      logGroupName: `/aws/lambda/mdx-tenant-provisioner-aws-${envName}`,
      retention: logRetention,
      removalPolicy,
      encryptionKey: platformCmk,
    });

    this.awsResourcesLambda = new lambda.Function(this, 'AwsResourcesLambda', {
      ...commonLambdaProps,
      functionName: `mdx-tenant-provisioner-aws-${envName}`,
      description: 'Step 2: Create per-org KMS, IAM, SQS, EventBridge, S3 resources',
      code: lambda.Code.fromAsset(lambdaAssetPath),
      handler: 'aws_resources.handler',
      timeout: cdk.Duration.minutes(5),
      logGroup: awsResourcesLogGroup,
    } as lambda.FunctionProps);

    // ─────────────────────────────────────────────────────────────────────
    // 3c. HEALTHLAKE LAMBDA
    // ─────────────────────────────────────────────────────────────────────
    const healthlakeLogGroup = new logs.LogGroup(this, 'HealthlakeLogGroup', {
      logGroupName: `/aws/lambda/mdx-tenant-provisioner-healthlake-${envName}`,
      retention: logRetention,
      removalPolicy,
      encryptionKey: platformCmk,
    });

    this.healthlakeLambda = new lambda.Function(this, 'HealthlakeLambda', {
      ...commonLambdaProps,
      functionName: `mdx-tenant-provisioner-healthlake-${envName}`,
      description: 'Step 3: Create HealthLake FHIR datastore and wait for ACTIVE',
      code: lambda.Code.fromAsset(lambdaAssetPath),
      handler: 'healthlake.handler',
      timeout: cdk.Duration.minutes(15),  // HealthLake creation takes up to 20 min
      logGroup: healthlakeLogGroup,
      environment: {
        ...commonLambdaProps.environment,
        HL_POLL_INTERVAL_SECONDS: '30',
        HL_MAX_POLL_ATTEMPTS: '30',
      },
    } as lambda.FunctionProps);
    // ─────────────────────────────────────────────────────────────────────
    // 3d. SFTP LAMBDA
    // ─────────────────────────────────────────────────────────────────────
    const sftpLogGroup = new logs.LogGroup(this, 'SftpLogGroup', {
      logGroupName: `/aws/lambda/mdx-tenant-provisioner-sftp-${envName}`,
      retention: logRetention,
      removalPolicy,
      encryptionKey: platformCmk,
    });

    this.sftpLambda = new lambda.Function(this, 'SftpLambda', {
      ...commonLambdaProps,
      functionName: `mdx-tenant-provisioner-sftp-${envName}`,
      description: 'Step 4: Create Transfer Family SFTP server/user for org',
      code: lambda.Code.fromAsset(lambdaAssetPath),
      handler: 'sftp.handler',
      timeout: cdk.Duration.minutes(5),
      logGroup: sftpLogGroup,
    } as lambda.FunctionProps);

    // ─────────────────────────────────────────────────────────────────────
    // 3e. FINALIZE LAMBDA
    // ─────────────────────────────────────────────────────────────────────
    const finalizeLogGroup = new logs.LogGroup(this, 'FinalizeLogGroup', {
      logGroupName: `/aws/lambda/mdx-tenant-provisioner-finalize-${envName}`,
      retention: logRetention,
      removalPolicy,
      encryptionKey: platformCmk,
    });

    this.finalizeLambda = new lambda.Function(this, 'FinalizeLambda', {
      ...commonLambdaProps,
      functionName: `mdx-tenant-provisioner-finalize-${envName}`,
      description: 'Step 5: Write DynamoDB tenant record and publish SNS notification',
      code: lambda.Code.fromAsset(lambdaAssetPath),
      handler: 'finalize.handler',
      timeout: cdk.Duration.seconds(60),
      logGroup: finalizeLogGroup,
    } as lambda.FunctionProps);

    // ─────────────────────────────────────────────────────────────────────
    // 4. STEP FUNCTION STATE MACHINE
    //    Wire all states into mdx-org-provision-sfn
    // ─────────────────────────────────────────────────────────────────────

    // State: ValidateProvisioningRequest
    const validateState = new tasks.LambdaInvoke(this, 'ValidateProvisioningRequest', {
      lambdaFunction: this.validateLambda,
      comment: 'Validate provisioning request schema',
      // Use the full Lambda response payload as the next state input
      outputPath: '$.Payload',
      retryOnServiceExceptions: false,
    });

    // State: CreateAWSResources
    const createAWSResourcesState = new tasks.LambdaInvoke(this, 'CreateAWSResources', {
      lambdaFunction: this.awsResourcesLambda,
      comment: 'Create per-org KMS, IAM, SQS, EventBridge, S3 resources',
      outputPath: '$.Payload',
      retryOnServiceExceptions: true,
    }).addRetry({
      errors: ['States.TaskFailed'],
      interval: cdk.Duration.seconds(10),
      maxAttempts: 2,
      backoffRate: 2,
    });

    // State: CreateHealthLakeDatastore
    const createHealthLakeState = new tasks.LambdaInvoke(this, 'CreateHealthLakeDatastore', {
      lambdaFunction: this.healthlakeLambda,
      comment: 'Create HealthLake FHIR R4 datastore and wait for ACTIVE',
      outputPath: '$.Payload',
      retryOnServiceExceptions: true,
    }).addRetry({
      errors: ['States.TaskFailed'],
      interval: cdk.Duration.seconds(30),
      maxAttempts: 2,
      backoffRate: 2,
    });

    // State: CreateSFTPEndpoint
    const createSFTPState = new tasks.LambdaInvoke(this, 'CreateSFTPEndpoint', {
      lambdaFunction: this.sftpLambda,
      comment: 'Create Transfer Family SFTP server/user with per-org S3 mapping',
      outputPath: '$.Payload',
      retryOnServiceExceptions: true,
    }).addRetry({
      errors: ['States.TaskFailed'],
      interval: cdk.Duration.seconds(10),
      maxAttempts: 2,
      backoffRate: 2,
    });

    // State: FinalizeTenant
    const finalizeState = new tasks.LambdaInvoke(this, 'FinalizeTenant', {
      lambdaFunction: this.finalizeLambda,
      comment: 'Write DynamoDB tenant record and publish SNS welcome notification',
      outputPath: '$.Payload',
      retryOnServiceExceptions: true,
    }).addRetry({
      errors: ['States.TaskFailed'],
      interval: cdk.Duration.seconds(5),
      maxAttempts: 3,
      backoffRate: 2,
    });

    // Terminal state: ProvisioningFailed
    const provisioningFailedState = new sfn.Fail(this, 'ProvisioningFailed', {
      comment: 'Tenant provisioning failed',
      errorPath: sfn.JsonPath.stringAt('$.Error'),
      causePath: sfn.JsonPath.stringAt('$.Cause'),
    });

    // Terminal state: ProvisioningSucceeded
    const provisioningSucceededState = new sfn.Succeed(this, 'ProvisioningSucceeded', {
      comment: 'Tenant provisioned successfully',
    });

    // ── Wire the state chain ───────────────────────────────────────────────
    // States follow the design's 10-step provisioning sequence:
    //   ValidateProvisioningRequest
    //     → CreateAWSResources (KMS, IAM, SQS, EventBridge, S3)
    //     → CreateHealthLakeDatastore
    //     → CreateSFTPEndpoint
    //     → FinalizeTenant (DynamoDB + SNS)
    //     → ProvisioningSucceeded
    //
    // Any unhandled Lambda error transitions to ProvisioningFailed.

    validateState.addCatch(provisioningFailedState, {
      errors: ['States.ALL'],
      resultPath: '$',
    });

    createAWSResourcesState.addCatch(provisioningFailedState, {
      errors: ['States.ALL'],
      resultPath: '$',
    });

    createHealthLakeState.addCatch(provisioningFailedState, {
      errors: ['States.ALL'],
      resultPath: '$',
    });

    createSFTPState.addCatch(provisioningFailedState, {
      errors: ['States.ALL'],
      resultPath: '$',
    });

    finalizeState.addCatch(provisioningFailedState, {
      errors: ['States.ALL'],
      resultPath: '$',
    });

    const definition = validateState
      .next(createAWSResourcesState)
      .next(createHealthLakeState)
      .next(createSFTPState)
      .next(finalizeState)
      .next(provisioningSucceededState);

    // ── Step Function execution log group ─────────────────────────────────
    const sfnLogGroup = new logs.LogGroup(this, 'ProvisioningSfnLogGroup', {
      logGroupName: `/aws/states/mdx-org-provision-sfn-${envName}`,
      retention: logRetention,
      removalPolicy,
      encryptionKey: platformCmk,
    });

    // ── Step Function IAM role ─────────────────────────────────────────────
    const sfnRole = new iam.Role(this, 'ProvisioningSfnRole', {
      roleName: `mdx-provision-sfn-role-${envName}`,
      assumedBy: new iam.ServicePrincipal('states.amazonaws.com'),
      description: 'Execution role for mdx-org-provision-sfn Step Function',
    });

    // Grant the Step Function permission to invoke all provisioner Lambdas
    [
      this.validateLambda,
      this.awsResourcesLambda,
      this.healthlakeLambda,
      this.sftpLambda,
      this.finalizeLambda,
    ].forEach(fn => fn.grantInvoke(sfnRole));

    // Grant CloudWatch Logs write access for execution logging
    sfnRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogsAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogDelivery',
          'logs:GetLogDelivery',
          'logs:UpdateLogDelivery',
          'logs:DeleteLogDelivery',
          'logs:ListLogDeliveries',
          'logs:PutResourcePolicy',
          'logs:DescribeResourcePolicies',
          'logs:DescribeLogGroups',
        ],
        resources: ['*'],
      }),
    );

    // Grant X-Ray tracing permission for Step Functions
    if (envConfig.enableXRay) {
      sfnRole.addToPolicy(
        new iam.PolicyStatement({
          sid: 'XRayAccess',
          effect: iam.Effect.ALLOW,
          actions: [
            'xray:PutTraceSegments',
            'xray:PutTelemetryRecords',
            'xray:GetSamplingRules',
            'xray:GetSamplingTargets',
          ],
          resources: ['*'],
        }),
      );
    }

    // ── Create the Step Function ───────────────────────────────────────────
    this.provisioningSfn = new sfn.StateMachine(this, 'ProvisioningSfn', {
      stateMachineName: `mdx-org-provision-sfn-${envName}`,
      stateMachineType: sfn.StateMachineType.STANDARD,
      definitionBody: sfn.DefinitionBody.fromChainable(definition),
      role: sfnRole,
      tracingEnabled: envConfig.enableXRay ?? true,
      logs: {
        destination: sfnLogGroup,
        level: sfn.LogLevel.ERROR,
        includeExecutionData: false,  // avoid logging PHI in Step Function logs
      },
      timeout: cdk.Duration.minutes(30),  // generous timeout for HealthLake (~20 min)
      comment: 'Medyrax™ tenant provisioning workflow (Req 8.1, 8.2)',
    });

    // ─────────────────────────────────────────────────────────────────────
    // 5. STACK TAGS
    // ─────────────────────────────────────────────────────────────────────
    cdk.Tags.of(this).add('Project', 'Medyrax');
    cdk.Tags.of(this).add('Layer', 'TenantManagement');
    cdk.Tags.of(this).add('Environment', envName);

    // ─────────────────────────────────────────────────────────────────────
    // 6. CLOUDFORMATION OUTPUTS
    // ─────────────────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ProvisioningSfnArn', {
      value: this.provisioningSfn.stateMachineArn,
      description: 'mdx-org-provision-sfn Step Function ARN',
      exportName: `mdx-provision-sfn-arn-${envName}`,
    });

    new cdk.CfnOutput(this, 'WelcomeSnsTopicArn', {
      value: this.welcomeSnsTopic.topicArn,
      description: 'SNS topic ARN for tenant provisioning welcome notifications',
      exportName: `mdx-welcome-sns-topic-arn-${envName}`,
    });

    new cdk.CfnOutput(this, 'ValidateLambdaArn', {
      value: this.validateLambda.functionArn,
      description: 'tenant-provisioner-validate Lambda ARN',
      exportName: `mdx-provisioner-validate-arn-${envName}`,
    });

    new cdk.CfnOutput(this, 'FinalizeLambdaArn', {
      value: this.finalizeLambda.functionArn,
      description: 'tenant-provisioner-finalize Lambda ARN',
      exportName: `mdx-provisioner-finalize-arn-${envName}`,
    });
  }
}
