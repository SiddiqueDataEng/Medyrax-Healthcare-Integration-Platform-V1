import * as cdk from 'aws-cdk-lib';
import * as sfn from 'aws-cdk-lib/aws-stepfunctions';
import * as tasks from 'aws-cdk-lib/aws-stepfunctions-tasks';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '@mdx/types';
import { MedyraxSecurityStack } from './MedyraxSecurityStack';
import { MedyraxDataStack } from './MedyraxDataStack';

/**
 * Props for the Tenant Stack.
 */
export interface MedyraxTenantStackProps extends MedyraxStackProps {
  securityStack: MedyraxSecurityStack;
  dataStack: MedyraxDataStack;
}

/**
 * Medyrax™ Tenant Stack
 *
 * Provisions the provisioning workflow infrastructure:
 * - The Step Functions state machine for org provisioning
 *   (mdx-org-provision-sfn — Task 4.2 provides full Lambda implementations)
 * - Scaffold for the deprovisioning Lambda (Task 4.4)
 * - Placeholder Lambda function definitions that will be fully implemented
 *   in Task 4
 *
 * Design reference (Multi-Tenant Management):
 *   "Provisioning Step Function (mdx-org-provision-sfn): 10 states from
 *    ValidateProvisioningRequest to SendWelcomeNotification"
 *
 * Requirements 8.1, 8.2, 8.3, 8.4
 */
export class MedyraxTenantStack extends cdk.Stack {

  /** ARN of the provisioning Step Function. */
  public readonly provisioningStateMachineArn: string;

  constructor(scope: Construct, id: string, props: MedyraxTenantStackProps) {
    super(scope, id, props);

    const { envName, dataStack, securityStack } = props;

    const logGroup = new logs.LogGroup(this, 'ProvisioningSfnLogGroup', {
      logGroupName: `/Medyrax/${envName}/sfn/provisioning`,
      retention:    logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // ── Placeholder Pass states for Step Function scaffold ────────────────────
    // Full Lambda implementations are in Task 4.2.
    // These Pass states allow the state machine to deploy now; they will be
    // replaced with Lambda invocation states in Task 4.

    const validateState = new sfn.Pass(this, 'ValidateProvisioningRequest', {
      comment: 'Placeholder — replaced by tenant-provisioner-validate Lambda in Task 4',
      resultPath: '$.validation',
    });

    const createKmsKeyState = new sfn.Pass(this, 'CreateKMSKey', {
      comment: 'Placeholder — calls CreateKey API in Task 4',
      resultPath: '$.kms',
    });

    const createIamRoleState = new sfn.Pass(this, 'CreateIAMRole', {
      comment: 'Placeholder — creates per-org IAM role in Task 4',
      resultPath: '$.iam',
    });

    const createSqsQueuesState = new sfn.Pass(this, 'CreateSQSQueues', {
      comment: 'Placeholder — creates SQS FIFO + DLQ in Task 4',
      resultPath: '$.sqs',
    });

    const createEventBridgeState = new sfn.Pass(this, 'CreateEventBridgeBusAndRules', {
      comment: 'Placeholder — creates EventBridge bus and routing rules in Task 4',
      resultPath: '$.eventbridge',
    });

    const createHealthLakeState = new sfn.Pass(this, 'CreateHealthLakeDataStore', {
      comment: 'Placeholder — calls HealthLake CreateFHIRDatastore in Task 4',
      resultPath: '$.healthlake',
    });

    const createSftpState = new sfn.Pass(this, 'CreateSFTPEndpoint', {
      comment: 'Placeholder — calls Transfer Family CreateServer in Task 4',
      resultPath: '$.sftp',
    });

    const createS3State = new sfn.Pass(this, 'CreateS3PrefixesAndBucketPolicies', {
      comment: 'Placeholder — creates per-org S3 prefixes + bucket policies in Task 4',
      resultPath: '$.s3',
    });

    const storeTenantConfigState = new sfn.Pass(this, 'StoreTenantConfig', {
      comment: 'Placeholder — writes complete tenant record to mdx-tenants DynamoDB in Task 4',
      resultPath: '$.tenant',
    });

    const sendWelcomeState = new sfn.Pass(this, 'SendWelcomeNotification', {
      comment: 'Placeholder — publishes SNS welcome notification in Task 4',
      resultPath: '$.notification',
    });

    // Chain the 10 provisioning states
    const provisioningDefinition = sfn.Chain.start(validateState)
      .next(createKmsKeyState)
      .next(createIamRoleState)
      .next(createSqsQueuesState)
      .next(createEventBridgeState)
      .next(createHealthLakeState)
      .next(createSftpState)
      .next(createS3State)
      .next(storeTenantConfigState)
      .next(sendWelcomeState);

    const provisioningStateMachine = new sfn.StateMachine(this, 'ProvisioningStateMachine', {
      stateMachineName: `mdx-org-provision-sfn-${envName}`,
      definition:       provisioningDefinition,
      stateMachineType: sfn.StateMachineType.STANDARD,
      timeout:          cdk.Duration.minutes(10),  // Requirement 8.1: complete within 5 minutes
      tracingEnabled:   true,
      logs: {
        destination:         logGroup,
        level:               sfn.LogLevel.ALL,
        includeExecutionData: true,
      },
    });

    this.provisioningStateMachineArn = provisioningStateMachine.stateMachineArn;

    // ── CloudFormation Outputs ────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'ProvisioningStateMachineArn', {
      value:      provisioningStateMachine.stateMachineArn,
      exportName: `MDX-ProvisioningStateMachineArn-${envName}`,
    });
  }
}
