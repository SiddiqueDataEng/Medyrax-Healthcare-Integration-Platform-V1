import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as kms from 'aws-cdk-lib/aws-kms';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '../types';

/**
 * Props specific to the Data Stack.
 */
export interface MedyraxDataStackProps extends MedyraxStackProps {
  /** ARN of the platform admin KMS CMK from the Security Stack. */
  platformAdminKeyArn: string;
}

/**
 * Medyrax™ Data Stack
 *
 * Provisions all shared platform data resources:
 * - DynamoDB tables (all with PITR + KMS encryption)
 * - Platform-level S3 buckets
 * - AWS HealthLake placeholder configuration
 *
 * Per-org S3 prefixes and SQS queues are provisioned by the Tenant Stack.
 *
 * Design reference (Data Stack):
 *   "Create DynamoDB tables: hb-fhir-id-registry, hb-tenants,
 *    hb-transformation-audit, hb-terminology-codes, hb-deident-mapping,
 *    hb-cds-rules — all with point-in-time recovery and per-org CMK encryption"
 *
 * Task 3.1 implements the full HipaaCompliantBucket construct and full table
 * configurations. This stack provides the table ARNs for downstream stacks.
 */
export class MedyraxDataStack extends cdk.Stack {

  // ── DynamoDB Table references ─────────────────────────────────────────────
  public readonly fhirIdRegistryTable: dynamodb.Table;
  public readonly tenantsTable: dynamodb.Table;
  public readonly transformationAuditTable: dynamodb.Table;
  public readonly terminologyCodesTable: dynamodb.Table;
  public readonly deidentMappingTable: dynamodb.Table;
  public readonly cdsRulesTable: dynamodb.Table;
  public readonly rbacPermissionsTable: dynamodb.Table;

  // ── S3 Bucket references ──────────────────────────────────────────────────
  public readonly terminologySnapshotsBucket: s3.Bucket;
  public readonly transformationRulesBucket: s3.Bucket;
  public readonly analyticsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: MedyraxDataStackProps) {
    super(scope, id, props);

    const { envName, platformAdminKeyArn } = props;

    const platformKey = kms.Key.fromKeyArn(
      this, 'PlatformAdminKey', platformAdminKeyArn
    );

    const tableRemovalPolicy = envName === 'prod' || envName === 'staging'
      ? cdk.RemovalPolicy.RETAIN
      : cdk.RemovalPolicy.DESTROY;

    // ── Helper: create a HIPAA-compliant DynamoDB table ──────────────────────
    const makeTable = (
      id: string,
      tableName: string,
      partitionKey: dynamodb.Attribute,
      sortKey?: dynamodb.Attribute,
      ttlAttributeName?: string
    ): dynamodb.Table => {
      const table = new dynamodb.Table(this, id, {
        tableName,
        partitionKey,
        sortKey,
        billingMode:          dynamodb.BillingMode.PAY_PER_REQUEST,
        encryption:           dynamodb.TableEncryption.CUSTOMER_MANAGED,
        encryptionKey:        platformKey,
        pointInTimeRecovery:  true,   // Requirement 7.1, Task 3.2 snapshot test
        removalPolicy:        tableRemovalPolicy,
        timeToLiveAttribute:  ttlAttributeName,
        stream:               dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
      });
      cdk.Tags.of(table).add('HIPAA', 'PHI');
      return table;
    };

    // ── 1. FHIR ID Registry ───────────────────────────────────────────────────
    // Design: "hb-fhir-id-registry: maps client IDs to HealthLake logical IDs"
    this.fhirIdRegistryTable = makeTable(
      'FhirIdRegistryTable',
      `hb-fhir-id-registry-${envName}`,
      { name: 'pk', type: dynamodb.AttributeType.STRING },   // orgId#{fhirResourceType}
      { name: 'sk', type: dynamodb.AttributeType.STRING }    // clientId
    );

    // GSI: lookup by healthLakeId
    this.fhirIdRegistryTable.addGlobalSecondaryIndex({
      indexName:    'gsi-healthlake-id',
      partitionKey: { name: 'healthLakeId', type: dynamodb.AttributeType.STRING },
    });

    // ── 2. Tenants ────────────────────────────────────────────────────────────
    // Design: "hb-tenants: tenant configuration and integration profiles"
    this.tenantsTable = makeTable(
      'TenantsTable',
      `hb-tenants-${envName}`,
      { name: 'orgId', type: dynamodb.AttributeType.STRING },
      { name: 'sk',    type: dynamodb.AttributeType.STRING }   // "CONFIG" | "PROFILE#{profileId}"
    );

    // ── 3. Transformation Audit ───────────────────────────────────────────────
    // Design: "hb-transformation-audit: TTL = timestamp + 7 years (HIPAA retention)"
    // Requirement 13.5: audit record must contain sourceId, targetId, rulesetVersion, timestamp
    this.transformationAuditTable = makeTable(
      'TransformationAuditTable',
      `hb-transformation-audit-${envName}`,
      { name: 'pk',  type: dynamodb.AttributeType.STRING },  // orgId#{messageControlId}
      { name: 'sk',  type: dynamodb.AttributeType.STRING },  // timestamp (ISO-8601)
      'ttl'                                                   // TTL = timestamp + 7 years
    );

    // ── 4. Terminology Codes ──────────────────────────────────────────────────
    // Design: "partition key {codeSystem}#{code}, attributes: display, synonyms, status"
    this.terminologyCodesTable = makeTable(
      'TerminologyCodesTable',
      `hb-terminology-codes-${envName}`,
      { name: 'pk', type: dynamodb.AttributeType.STRING },  // {codeSystem}#{code}
      { name: 'sk', type: dynamodb.AttributeType.STRING }   // version (e.g. "2024-01")
    );

    // GSI: query by code system for bulk refresh
    this.terminologyCodesTable.addGlobalSecondaryIndex({
      indexName:    'gsi-code-system',
      partitionKey: { name: 'codeSystem', type: dynamodb.AttributeType.STRING },
      sortKey:      { name: 'code',       type: dynamodb.AttributeType.STRING },
    });

    // ── 5. De-identification Mapping ──────────────────────────────────────────
    // Design: "encrypted lookup table accessible only to Platform_Admin role"
    // Requirement 11.4: maps de-identified analytics IDs to original FHIR IDs
    this.deidentMappingTable = makeTable(
      'DeidentMappingTable',
      `hb-deident-mapping-${envName}`,
      { name: 'deidentId', type: dynamodb.AttributeType.STRING }
    );

    // GSI: reverse lookup (original → de-identified)
    this.deidentMappingTable.addGlobalSecondaryIndex({
      indexName:    'gsi-original-fhir-id',
      partitionKey: { name: 'originalFhirId', type: dynamodb.AttributeType.STRING },
    });

    // ── 6. CDS Rules ──────────────────────────────────────────────────────────
    // Design: "hb-cds-rules: FHIRPath conditions and ClinicalImpression templates per org"
    this.cdsRulesTable = makeTable(
      'CdsRulesTable',
      `hb-cds-rules-${envName}`,
      { name: 'orgId',  type: dynamodb.AttributeType.STRING },
      { name: 'ruleId', type: dynamodb.AttributeType.STRING }
    );

    // ── 7. RBAC Permissions ───────────────────────────────────────────────────
    // Used by the RBAC enforcement middleware (Task 13.2)
    this.rbacPermissionsTable = makeTable(
      'RbacPermissionsTable',
      `hb-rbac-permissions-${envName}`,
      { name: 'roleName',   type: dynamodb.AttributeType.STRING },
      { name: 'permission', type: dynamodb.AttributeType.STRING }
    );

    // ── S3 Buckets (platform-level, no org isolation needed) ─────────────────

    // Terminology code set snapshots for weekly refresh
    this.terminologySnapshotsBucket = new s3.Bucket(this, 'TerminologySnapshotsBucket', {
      bucketName:        `hb-terminology-snapshots-${this.account}-${envName}`,
      encryption:        s3.BucketEncryption.KMS,
      encryptionKey:     platformKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned:         true,
      enforceSSL:        true,
      removalPolicy:     tableRemovalPolicy,
    });

    // HL7→FHIR transformation rulesets (loaded by Lambda on cold start)
    this.transformationRulesBucket = new s3.Bucket(this, 'TransformationRulesBucket', {
      bucketName:        `hb-transformation-rules-${this.account}-${envName}`,
      encryption:        s3.BucketEncryption.KMS,
      encryptionKey:     platformKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned:         true,
      enforceSSL:        true,
      removalPolicy:     tableRemovalPolicy,
    });

    // Shared analytics output bucket (partitioned by resourceType/orgId/date)
    this.analyticsBucket = new s3.Bucket(this, 'AnalyticsBucket', {
      bucketName:        `hb-analytics-${this.account}-${envName}`,
      encryption:        s3.BucketEncryption.KMS,
      encryptionKey:     platformKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned:         true,
      enforceSSL:        true,
      removalPolicy:     tableRemovalPolicy,
      lifecycleRules: [
        {
          transitions: [
            { storageClass: s3.StorageClass.INTELLIGENT_TIERING, transitionAfter: cdk.Duration.days(90) },
          ],
        },
      ],
    });

    // ── CloudFormation Outputs ────────────────────────────────────────────────
    new cdk.CfnOutput(this, 'TenantsTableArn', {
      value:      this.tenantsTable.tableArn,
      exportName: `HB-TenantsTableArn-${envName}`,
    });
    new cdk.CfnOutput(this, 'FhirIdRegistryTableArn', {
      value:      this.fhirIdRegistryTable.tableArn,
      exportName: `HB-FhirIdRegistryTableArn-${envName}`,
    });
    new cdk.CfnOutput(this, 'TransformationRulesBucketName', {
      value:      this.transformationRulesBucket.bucketName,
      exportName: `HB-TransformationRulesBucketName-${envName}`,
    });
    new cdk.CfnOutput(this, 'AnalyticsBucketName', {
      value:      this.analyticsBucket.bucketName,
      exportName: `HB-AnalyticsBucketName-${envName}`,
    });
  }
}
