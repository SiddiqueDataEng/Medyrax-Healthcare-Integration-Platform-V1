package com.Medyrax.common.tenant;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Canonical tenant (Connected_Organization) configuration POJO.
 *
 * <p>Mirrors the DynamoDB {@code hb-tenants} table schema defined in the design doc.
 * All Lambda functions call {@code TenantConfigService.getTenantConfig(orgId)} to
 * obtain an instance of this class before processing any request.
 *
 * <p>Design reference (Multi-Tenant Management section):
 * "Tenant lookup with DynamoDB-level encryption via per-org CMK"
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@JsonInclude(JsonInclude.Include.NON_NULL)
public class TenantContext {

    // ── Identity ─────────────────────────────────────────────────────────────
    /** Primary identifier for the Connected_Organization. */
    private String orgId;

    /** Human-readable organization name. */
    private String orgName;

    /** Lifecycle status: active | suspended | deprovisioned. */
    private String status;

    // ── AWS Resources ─────────────────────────────────────────────────────────
    /** ARN of the per-org KMS CMK used for at-rest encryption. */
    private String kmsKeyArn;

    /** ARN of the per-org IAM execution role for Lambda functions. */
    private String iamRoleArn;

    /** ARN of the per-org EventBridge custom bus. */
    private String eventBusArn;

    /** URL of the per-org SQS FIFO primary queue. */
    private String sqsFifoQueueUrl;

    /** URL of the per-org SQS alert queue. */
    private String sqsAlertQueueUrl;

    /** URL of the per-org dead-letter queue. */
    private String sqsDlqUrl;

    // ── HealthLake ─────────────────────────────────────────────────────────────
    /** AWS HealthLake FHIR datastore ID for this tenant. */
    private String healthLakeDataStoreId;

    // ── File Integration ───────────────────────────────────────────────────────
    /** AWS Transfer Family SFTP server ID for this tenant. */
    private String sftpServerId;

    /** S3 bucket name for inbound files. */
    private String s3InputBucket;

    /** S3 prefix for inbound files (e.g. "hb-{orgId}-inbound/"). */
    private String s3InputPrefix;

    /** S3 bucket name for outbound files. */
    private String s3OutputBucket;

    /** S3 prefix for outbound files (e.g. "hb-{orgId}-outbound/"). */
    private String s3OutputPrefix;

    /** S3 bucket for validation reports and quarantine. */
    private String s3ReportsBucket;

    // ── Notifications ──────────────────────────────────────────────────────────
    /** Webhook URL for outbound event delivery (Requirement 5.7). */
    private String webhookUrl;

    /** Alert email address for file validation failures and critical alerts. */
    private String alertEmail;

    /** ARN of the SNS topic for alert notifications. */
    private String alertSnsTopicArn;

    // ── Configuration ─────────────────────────────────────────────────────────
    /** Cognito session timeout in minutes (default 15). Requirement 7.7. */
    @Builder.Default
    private int sessionTimeoutMinutes = 15;

    /** KMS key rotation period in days (default 365). Requirement 7.6. */
    @Builder.Default
    private int kmsRotationDays = 365;

    /** Analytics export schedule in minutes (default 30). Requirement 11.1. */
    @Builder.Default
    private int analyticsScheduleMinutes = 30;

    // ── Timestamps ────────────────────────────────────────────────────────────
    /** ISO-8601 timestamp when this tenant was provisioned. */
    private String provisionedAt;

    /** ISO-8601 timestamp when this tenant was deprovisioned (null if active). */
    private String deprovisionedAt;

    /**
     * Returns {@code true} if this tenant is in the {@code active} status and
     * can process requests.
     */
    public boolean isActive() {
        return "active".equalsIgnoreCase(status);
    }

    /**
     * Returns {@code true} if this tenant has been deprovisioned.
     */
    public boolean isDeprovisioned() {
        return "deprovisioned".equalsIgnoreCase(status);
    }
}
