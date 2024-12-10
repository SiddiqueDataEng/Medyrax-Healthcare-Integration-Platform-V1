/**
 * LambdaEventWiring CDK Construct (task 23.2)
 *
 * Wires all Lambda functions to their respective SQS triggers and
 * EventBridge rules. This construct is the single source of truth
 * for all Lambda-to-queue and Lambda-to-bus bindings.
 *
 * Wiring map (per design spec):
 *
 *   SQS → Lambda:
 *     mdx-{orgId}-hl7-inbound.fifo      → hl7-parser
 *     mdx-{orgId}-hl7-parsed.fifo       → hl7-transformer
 *     mdx-{orgId}-healthlake-inbound    → healthlake-writer
 *     mdx-{orgId}-webhook-queue         → integration-bus-webhook
 *     mdx-{orgId}-file-inbound          → file-validator
 *     mdx-{orgId}-file-process          → file-processor
 *
 *   EventBridge → Lambda:
 *     fhir.resource.*                   → analytics-deidentify
 *     hl7.batch.completed               → (monitoring)
 *     healthlake.export.complete        → (monitoring)
 *     encounter.concluded               → telehealth-encounter-trigger
 *
 *   S3 → Lambda:
 *     mdx-{orgId}-inbound/ ObjectCreated → hl7-file-processor
 *     mdx-{orgId}-inbound/ ObjectCreated → file-detector
 *
 * Requirements: all integration requirements
 */
import * as cdk from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3n from 'aws-cdk-lib/aws-s3-notifications';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';

export interface LambdaEventWiringProps {
  /** Short environment name */
  envName: string;
  /** Connected_Organization ID to wire (can be called per-org during provisioning) */
  orgId: string;
  /** KMS key ARN for this org */
  kmsKeyArn: string;
  /** EventBridge custom bus for this org */
  eventBus: events.IEventBus;
  /** Lambda function references (pass in from outer stacks) */
  lambdas: {
    hl7Parser?: lambda.IFunction;
    hl7Transformer?: lambda.IFunction;
    hl7FileProcessor?: lambda.IFunction;
    healthlakeWriter?: lambda.IFunction;
    integrationBusWebhook?: lambda.IFunction;
    fileDetector?: lambda.IFunction;
    fileValidator?: lambda.IFunction;
    fileProcessor?: lambda.IFunction;
    analyticsDeidentify?: lambda.IFunction;
    telehealthEncounterTrigger?: lambda.IFunction;
  };
  /** S3 inbound bucket for this org */
  inboundBucket?: s3.IBucket;
  /** Removal policy */
  removalPolicy?: cdk.RemovalPolicy;
}

export class LambdaEventWiring extends Construct {

  constructor(scope: Construct, id: string, props: LambdaEventWiringProps) {
    super(scope, id);

    const {
      envName, orgId, kmsKeyArn, eventBus,
      lambdas, inboundBucket,
      removalPolicy = cdk.RemovalPolicy.DESTROY,
    } = props;
    const cmk = kms.Key.fromKeyArn(this, 'OrgCmkRef', kmsKeyArn);

    // ── Helper: create SQS FIFO queue and wire to Lambda ──────────────────
    const wireQueue = (
      queueId: string,
      queueName: string,
      fn: lambda.IFunction | undefined,
      fifo = true,
      batchSize = 10,
    ): sqs.Queue | null => {
      if (!fn) return null;

      const dlq = new sqs.Queue(this, `${queueId}Dlq`, {
        queueName: fifo ? `${queueName}-dlq.fifo` : `${queueName}-dlq`,
        fifo,
        encryption: sqs.QueueEncryption.KMS,
        encryptionMasterKey: cmk,
        removalPolicy,
      });

      const queue = new sqs.Queue(this, queueId, {
        queueName: fifo ? `${queueName}.fifo` : queueName,
        fifo,
        contentBasedDeduplication: false,
        encryption: sqs.QueueEncryption.KMS,
        encryptionMasterKey: cmk,
        visibilityTimeout: cdk.Duration.seconds(300),
        deadLetterQueue: { maxReceiveCount: 3, queue: dlq },
        removalPolicy,
      });

      fn.addEventSource(new lambdaEventSources.SqsEventSource(queue, {
        batchSize,
        reportBatchItemFailures: true,
      }));

      return queue;
    };

    // ── SQS → Lambda bindings ─────────────────────────────────────────────

    // hl7-inbound.fifo → hl7-parser
    wireQueue(
      'Hl7InboundQueue',
      `mdx-${orgId}-hl7-inbound`,
      lambdas.hl7Parser,
      true, 10,
    );

    // hl7-healthlake-inbound → healthlake-writer (standard queue, not FIFO)
    wireQueue(
      'HealthlakeInboundQueue',
      `mdx-${orgId}-healthlake-inbound`,
      lambdas.healthlakeWriter,
      false, 5,
    );

    // webhook-queue → integration-bus-webhook (standard)
    wireQueue(
      'WebhookQueue',
      `mdx-${orgId}-webhook-queue`,
      lambdas.integrationBusWebhook,
      false, 1,
    );

    // file-inbound → file-validator (standard)
    wireQueue(
      'FileInboundQueue',
      `mdx-${orgId}-file-inbound`,
      lambdas.fileValidator,
      false, 5,
    );

    // file-process → file-processor (standard)
    wireQueue(
      'FileProcessQueue',
      `mdx-${orgId}-file-process`,
      lambdas.fileProcessor,
      false, 5,
    );

    // ── EventBridge → Lambda bindings ────────────────────────────────────

    // fhir.resource.* → analytics-deidentify
    if (lambdas.analyticsDeidentify) {
      new events.Rule(this, 'FhirToAnalyticsRule', {
        eventBus,
        ruleName: `mdx-${orgId}-fhir-to-analytics`,
        description: `Route FHIR events to analytics de-identification for org ${orgId}`,
        eventPattern: {
          source: [{ prefix: 'medyrax.' }],
          detailType: ['fhir.resource.created', 'fhir.resource.updated'],
          detail: { orgId: [orgId] },
        },
        targets: [new targets.LambdaFunction(lambdas.analyticsDeidentify)],
      });
    }

    // encounter.concluded → telehealth-encounter-trigger
    if (lambdas.telehealthEncounterTrigger) {
      new events.Rule(this, 'EncounterConcludedRule', {
        eventBus,
        ruleName: `mdx-${orgId}-encounter-concluded`,
        eventPattern: {
          source: ['medyrax.telehealth'],
          detailType: ['encounter.concluded'],
          detail: { orgId: [orgId] },
        },
        targets: [new targets.LambdaFunction(lambdas.telehealthEncounterTrigger)],
      });
    }

    // ── S3 → Lambda bindings ──────────────────────────────────────────────

    if (inboundBucket) {
      // S3 ObjectCreated → file-detector
      if (lambdas.fileDetector) {
        inboundBucket.addEventNotification(
          s3.EventType.OBJECT_CREATED,
          new s3n.LambdaDestination(lambdas.fileDetector),
          { prefix: `mdx-${orgId}-inbound/` },
        );
      }

      // S3 ObjectCreated → hl7-file-processor (for batch HL7 files)
      if (lambdas.hl7FileProcessor) {
        inboundBucket.addEventNotification(
          s3.EventType.OBJECT_CREATED,
          new s3n.LambdaDestination(lambdas.hl7FileProcessor),
          { prefix: `mdx-${orgId}-inbound/`, suffix: '.hl7' },
        );
      }
    }
  }
}
