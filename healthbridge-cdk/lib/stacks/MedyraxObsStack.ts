import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import * as cwactions from 'aws-cdk-lib/aws-cloudwatch-actions';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '@mdx/types';
import { MedyraxCoreStack } from './MedyraxCoreStack';

/**
 * Props for the Observability Stack.
 */
export interface MedyraxObsStackProps extends MedyraxStackProps {
  coreStack: MedyraxCoreStack;
}

/**
 * Medyrax™ Observability Stack
 *
 * Provisions CloudWatch alarms, dashboards, and SNS alert topics.
 * Individual metric alarms for Lambda functions and queues are added in
 * subsequent tasks (5–20) when those resources are created.
 *
 * Design reference (Observability section):
 *   "CloudWatch alarms: ErrorRateHigh, LatencyBreach-MLLP,
 *    LatencyBreach-FHIR, LatencyBreach-File, DLQDepthHigh"
 *
 * Requirements 14.1 – 14.7
 */
export class MedyraxObsStack extends cdk.Stack {

  /** SNS topic for critical/high-severity operational alarms. */
  public readonly criticalAlarmsTopic: sns.Topic;

  /** SNS topic for info-level operational notifications. */
  public readonly infoAlarmsTopic: sns.Topic;

  /** The main CloudWatch dashboard for integration health. */
  public readonly integrationDashboard: cloudwatch.Dashboard;

  constructor(scope: Construct, id: string, props: MedyraxObsStackProps) {
    super(scope, id, props);

    const { envName, envConfig } = props;

    // ── SNS Alert Topics ─────────────────────────────────────────────────────
    this.criticalAlarmsTopic = new sns.Topic(this, 'CriticalAlarmsTopic', {
      topicName:    `mdx-critical-alarms-${envName}`,
      displayName:  'Medyrax™ Critical Alarms',
    });

    this.infoAlarmsTopic = new sns.Topic(this, 'InfoAlarmsTopic', {
      topicName:    `mdx-info-alarms-${envName}`,
      displayName:  'Medyrax™ Info Notifications',
    });

    // Wire PagerDuty SNS topic if configured
    if (envConfig.pagerDutySnsTopicArn) {
      const pagerDutyTopic = sns.Topic.fromTopicArn(
        this, 'PagerDutyTopic', envConfig.pagerDutySnsTopicArn
      );
      this.criticalAlarmsTopic.addSubscription(
        new subscriptions.SnsSubscription(pagerDutyTopic)
      );
    }

    // ── CloudWatch Dashboard ─────────────────────────────────────────────────
    // Requirement 14.5: refresh at maximum 60-second interval
    this.integrationDashboard = new cloudwatch.Dashboard(this, 'IntegrationDashboard', {
      dashboardName: `Medyrax-Integration-Health-${envName}`,
      periodOverride: cloudwatch.PeriodOverride.REAL_TIME,
    });

    // API Gateway 4xx/5xx error rate widget (platform-wide)
    const apiErrorRateWidget = new cloudwatch.GraphWidget({
      title:  'API Gateway Error Rate',
      width:  12,
      height: 6,
      left: [
        new cloudwatch.Metric({
          namespace:  'AWS/ApiGateway',
          metricName: '4XXError',
          dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
          statistic:  'Sum',
          period:     cdk.Duration.minutes(1),
          label:      '4xx Errors',
        }),
        new cloudwatch.Metric({
          namespace:  'AWS/ApiGateway',
          metricName: '5XXError',
          dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
          statistic:  'Sum',
          period:     cdk.Duration.minutes(1),
          label:      '5xx Errors',
        }),
      ],
    });

    const apiLatencyWidget = new cloudwatch.GraphWidget({
      title:  'API Gateway Latency (p95, p99)',
      width:  12,
      height: 6,
      left: [
        new cloudwatch.Metric({
          namespace:  'AWS/ApiGateway',
          metricName: 'Latency',
          dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
          statistic:  'p95',
          period:     cdk.Duration.minutes(1),
          label:      'p95 Latency',
        }),
        new cloudwatch.Metric({
          namespace:  'AWS/ApiGateway',
          metricName: 'Latency',
          dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
          statistic:  'p99',
          period:     cdk.Duration.minutes(1),
          label:      'p99 Latency',
        }),
      ],
      rightAnnotations: [
        // Requirement 14.3: FHIR API latency SLA = 500ms
        { label: 'FHIR SLA (500ms)', value: 500, color: '#ff0000' },
      ],
    });

    this.integrationDashboard.addWidgets(apiErrorRateWidget, apiLatencyWidget);

    // ── API Gateway Latency Breach Alarm ─────────────────────────────────────
    // Requirement 14.3: FHIR API p99 > 500ms
    const fhirLatencyAlarm = new cloudwatch.Alarm(this, 'FhirLatencyBreachAlarm', {
      alarmName:          `MDX-LatencyBreach-FHIR-${envName}`,
      alarmDescription:   'FHIR API p99 latency exceeded 500ms SLA',
      metric: new cloudwatch.Metric({
        namespace:  'AWS/ApiGateway',
        metricName: 'Latency',
        dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
        statistic:  'p99',
        period:     cdk.Duration.minutes(1),
      }),
      threshold:           500,
      evaluationPeriods:   3,
      comparisonOperator:  cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData:    cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    fhirLatencyAlarm.addAlarmAction(new cwactions.SnsAction(this.criticalAlarmsTopic));

    // ── CloudFormation Outputs ────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'CriticalAlarmsTopicArn', {
      value:      this.criticalAlarmsTopic.topicArn,
      exportName: `MDX-CriticalAlarmsTopicArn-${envName}`,
    });
    new cdk.CfnOutput(this, 'DashboardUrl', {
      value:      `https://${this.region}.console.aws.amazon.com/cloudwatch/home#dashboards:name=Medyrax-Integration-Health-${envName}`,
      exportName: `MDX-DashboardUrl-${envName}`,
    });
  }
}
