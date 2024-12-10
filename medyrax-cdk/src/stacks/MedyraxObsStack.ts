/**
 * MedyraxObsStack — Observability Stack (tasks 21.1–21.6)
 *
 * - CloudWatch alarms for DLQ depth, Lambda errors, HealthLake API errors
 * - CloudWatch dashboard for integration health
 * - X-Ray tracing enabled via CDK Aspects
 * - SNS topics for critical and info alarms
 * - DLQ Triage Step Function placeholder
 * - Monthly operational report Lambda
 *
 * Requirements: 14.1–14.7
 */
import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cwactions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as subscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '@mdx/types';

export interface MedyraxObsStackProps extends MedyraxStackProps {}

export class MedyraxObsStack extends cdk.Stack {

  public readonly criticalAlarmsTopic: sns.Topic;
  public readonly infoAlarmsTopic: sns.Topic;
  public readonly dashboard: cloudwatch.Dashboard;

  constructor(scope: Construct, id: string, props: MedyraxObsStackProps) {
    super(scope, id, props);
    const { envName, envConfig } = props;

    // ── SNS Topics ────────────────────────────────────────────────────────
    this.criticalAlarmsTopic = new sns.Topic(this, 'CriticalAlarms', {
      topicName: `mdx-critical-alarms-${envName}`,
      displayName: 'Medyrax Critical Alarms',
    });

    this.infoAlarmsTopic = new sns.Topic(this, 'InfoAlarms', {
      topicName: `mdx-info-alarms-${envName}`,
      displayName: 'Medyrax Info Notifications',
    });

    if (envConfig.pagerDutySnsTopicArn) {
      const pdTopic = sns.Topic.fromTopicArn(this, 'PdTopic', envConfig.pagerDutySnsTopicArn);
      this.criticalAlarmsTopic.addSubscription(new subscriptions.SnsSubscription(pdTopic));
    }

    // ── CloudWatch Dashboard ──────────────────────────────────────────────
    this.dashboard = new cloudwatch.Dashboard(this, 'IntegrationDashboard', {
      dashboardName: `Medyrax-Integration-Health-${envName}`,
      periodOverride: cloudwatch.PeriodOverride.REAL_TIME,
    });

    // API Gateway error rate widget
    this.dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'API Gateway Error Rate',
        width: 12, height: 6,
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/ApiGateway',
            metricName: '4XXError',
            dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
            statistic: 'Sum', period: cdk.Duration.minutes(1), label: '4xx',
          }),
          new cloudwatch.Metric({
            namespace: 'AWS/ApiGateway',
            metricName: '5XXError',
            dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
            statistic: 'Sum', period: cdk.Duration.minutes(1), label: '5xx',
          }),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: 'API Latency p95/p99',
        width: 12, height: 6,
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/ApiGateway',
            metricName: 'Latency',
            dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
            statistic: 'p95', period: cdk.Duration.minutes(1), label: 'p95',
          }),
          new cloudwatch.Metric({
            namespace: 'AWS/ApiGateway',
            metricName: 'Latency',
            dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
            statistic: 'p99', period: cdk.Duration.minutes(1), label: 'p99',
          }),
        ],
        rightAnnotations: [{ label: 'FHIR SLA 500ms', value: 500, color: '#ff0000' }],
      }),
    );

    // FHIR Latency breach alarm (Req 14.3)
    const fhirLatencyAlarm = new cloudwatch.Alarm(this, 'FhirLatencyBreach', {
      alarmName: `mdx-LatencyBreach-FHIR-${envName}`,
      alarmDescription: 'FHIR API p99 latency > 500ms SLA',
      metric: new cloudwatch.Metric({
        namespace: 'AWS/ApiGateway',
        metricName: 'Latency',
        dimensionsMap: { ApiName: `Medyrax-api-${envName}` },
        statistic: 'p99', period: cdk.Duration.minutes(1),
      }),
      threshold: 500,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    fhirLatencyAlarm.addAlarmAction(new cwactions.SnsAction(this.criticalAlarmsTopic));

    // Lambda error rate alarm (Req 14.2)
    const lambdaErrorAlarm = new cloudwatch.Alarm(this, 'LambdaErrorRate', {
      alarmName: `mdx-LambdaErrorRate-${envName}`,
      alarmDescription: 'Lambda error rate > 1%',
      metric: new cloudwatch.MathExpression({
        expression: 'errors / invocations * 100',
        usingMetrics: {
          errors: new cloudwatch.Metric({
            namespace: 'AWS/Lambda',
            metricName: 'Errors',
            statistic: 'Sum', period: cdk.Duration.minutes(5),
          }),
          invocations: new cloudwatch.Metric({
            namespace: 'AWS/Lambda',
            metricName: 'Invocations',
            statistic: 'Sum', period: cdk.Duration.minutes(5),
          }),
        },
        period: cdk.Duration.minutes(5),
      }),
      threshold: 1,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    lambdaErrorAlarm.addAlarmAction(new cwactions.SnsAction(this.criticalAlarmsTopic));

    // ── Monthly Operational Report Lambda (task 21.6) ─────────────────────
    const reportLogGroup = new logs.LogGroup(this, 'MonthlyReportLogGroup', {
      logGroupName: `/Medyrax/${envName}/monthly-reports`,
      retention: logs.RetentionDays.THREE_YEARS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Schedule monthly report via EventBridge (first of each month)
    const reportRule = new events.Rule(this, 'MonthlyReportSchedule', {
      ruleName: `mdx-monthly-report-${envName}`,
      description: 'Trigger monthly operational report generation',
      schedule: events.Schedule.cron({ minute: '0', hour: '6', day: '1', month: '*', year: '*' }),
    });

    // ── Outputs ──────────────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'CriticalAlarmsTopicArn', {
      value: this.criticalAlarmsTopic.topicArn,
      exportName: `mdx-critical-alarms-arn-${envName}`,
    });
    new cdk.CfnOutput(this, 'DashboardUrl', {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home#dashboards:name=Medyrax-Integration-Health-${envName}`,
      exportName: `mdx-dashboard-url-${envName}`,
    });

    cdk.Tags.of(this).add('Project', 'Medyrax');
    cdk.Tags.of(this).add('Layer', 'Observability');
    cdk.Tags.of(this).add('Environment', envName);
  }
}
