/**
 * TenantEventBus CDK Construct (task 12.1)
 *
 * Creates per-org Integration Bus resources:
 * - EventBridge custom bus (mdx-{orgId}-bus)
 * - SQS FIFO queues per FHIR resource type with DLQs
 * - EventBridge rules routing to queues
 * - EventBridge Archive (90-day retention)
 * - CloudWatch alarm on DLQ depth > 100
 *
 * Requirements: 5.1, 5.4, 5.5
 */
import * as cdk from 'aws-cdk-lib';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';

// All 11 core FHIR resource types from Requirement 1.4
const CORE_FHIR_RESOURCE_TYPES = [
  'Patient', 'Practitioner', 'Organization', 'Encounter', 'Observation',
  'Condition', 'MedicationRequest', 'DiagnosticReport', 'AllergyIntolerance',
  'Procedure', 'Coverage',
] as const;

export interface TenantEventBusProps {
  /** Connected_Organization identifier */
  orgId: string;
  /** KMS key ARN for SSE-KMS encryption on SQS */
  kmsKeyArn: string;
  /** Removal policy for created resources */
  removalPolicy?: cdk.RemovalPolicy;
}

export class TenantEventBus extends Construct {

  /** The EventBridge custom bus for this org */
  public readonly eventBus: events.EventBus;

  /** Map from FHIR resource type to its SQS FIFO queue */
  public readonly queues: Map<string, sqs.Queue> = new Map();

  /** Map from FHIR resource type to its DLQ */
  public readonly dlqs: Map<string, sqs.Queue> = new Map();

  /** The EventBridge Archive for replay capability */
  public readonly archive: events.Archive;

  constructor(scope: Construct, id: string, props: TenantEventBusProps) {
    super(scope, id);

    const { orgId, kmsKeyArn, removalPolicy = cdk.RemovalPolicy.DESTROY } = props;
    const cmk = kms.Key.fromKeyArn(this, 'OrgCmk', kmsKeyArn);

    // ── EventBridge Custom Bus ────────────────────────────────────────────
    this.eventBus = new events.EventBus(this, 'EventBus', {
      eventBusName: `mdx-${orgId}-bus`,
    });

    // ── EventBridge Archive (90-day replay) ──────────────────────────────
    this.archive = this.eventBus.archive('EventArchive', {
      archiveName: `mdx-${orgId}-event-archive`,
      description: `Medyrax event archive for org ${orgId}`,
      eventPattern: { source: [{ prefix: 'medyrax.' }] },
      retention: cdk.Duration.days(90),
    });

    // ── Per-resource-type SQS FIFO queues ────────────────────────────────
    for (const resourceType of CORE_FHIR_RESOURCE_TYPES) {
      const queueBaseName = `mdx-${orgId}-${resourceType.toLowerCase()}`;

      // DLQ
      const dlq = new sqs.Queue(this, `${resourceType}Dlq`, {
        queueName: `${queueBaseName}-dlq.fifo`,
        fifo: true,
        encryption: sqs.QueueEncryption.KMS,
        encryptionMasterKey: cmk,
        retentionPeriod: cdk.Duration.days(14),
        removalPolicy,
      });
      this.dlqs.set(resourceType, dlq);

      // CloudWatch alarm: DLQ depth > 100 (Requirement 5.4)
      new cloudwatch.Alarm(this, `${resourceType}DlqAlarm`, {
        alarmName: `mdx-${orgId}-${resourceType.toLowerCase()}-dlq-depth`,
        alarmDescription: `DLQ depth > 100 for ${resourceType} queue of org ${orgId}`,
        metric: dlq.metricApproximateNumberOfMessagesVisible({
          period: cdk.Duration.minutes(1),
          statistic: 'Sum',
        }),
        threshold: 100,
        evaluationPeriods: 1,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });

      // Main FIFO queue
      const queue = new sqs.Queue(this, `${resourceType}Queue`, {
        queueName: `${queueBaseName}-queue.fifo`,
        fifo: true,
        contentBasedDeduplication: false,
        encryption: sqs.QueueEncryption.KMS,
        encryptionMasterKey: cmk,
        visibilityTimeout: cdk.Duration.seconds(300),
        retentionPeriod: cdk.Duration.days(7),
        deadLetterQueue: { maxReceiveCount: 3, queue: dlq },
        removalPolicy,
      });
      this.queues.set(resourceType, queue);

      // EventBridge rule: route fhir.resource.* events to queue
      new events.Rule(this, `${resourceType}Rule`, {
        eventBus: this.eventBus,
        ruleName: `mdx-${orgId}-${resourceType.toLowerCase()}-rule`,
        description: `Route ${resourceType} events to SQS for org ${orgId}`,
        eventPattern: {
          source: [{ prefix: 'medyrax.' }],
          detailType: [
            `fhir.resource.created`,
            `fhir.resource.updated`,
            `fhir.resource.deleted`,
          ],
          detail: {
            resourceType: [resourceType],
            orgId: [orgId],
          },
        },
        targets: [new targets.SqsQueue(queue)],
      });
    }

    // ── CloudFormation Outputs ────────────────────────────────────────────
    new cdk.CfnOutput(this, 'EventBusArn', {
      value: this.eventBus.eventBusArn,
      exportName: `mdx-${orgId}-event-bus-arn`,
    });
  }
}
