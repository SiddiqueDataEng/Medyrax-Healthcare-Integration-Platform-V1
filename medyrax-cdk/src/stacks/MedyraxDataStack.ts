/**
 * MedyraxDataStack
 *
 * CDK Stack that provisions all stateful data-layer resources:
 *
 *   1. HipaaCompliantBucket — reusable SSE-KMS S3 construct (Requirements 7.1, 7.8, 9.7)
 *   2. DynamoDB tables (all with PITR and per-org CMK encryption):
 *        - mdx-fhir-id-registry        (Requirement 3.1)
 *        - mdx-tenants                  (Requirement 8.1–8.5)
 *        - mdx-transformation-audit     (Requirement 13.5)
 *        - mdx-terminology-codes        (Requirement 4.1, 4.4)
 *        - mdx-deident-mapping          (Requirement 11.4)
 *        - mdx-cds-rules                (Requirement 12.6)
 *   3. AWS HealthLake FHIR datastore placeholder via CfnFHIRDatastore
 *      (conditionally created when envConfig.enableHealthLake = true)
 *
 * The stack accepts a platformCmkArn prop forwarded from the Security Stack.
 * In multi-stack deployments, pass the ARN from MedyraxSecurityStack output.
 * For standalone/test usage a placeholder ARN may be supplied.
 *
 * Requirements: 3.1, 7.1, 7.8, 9.7, 11.4
 */
import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as healthlake from 'aws-cdk-lib/aws-healthlake';
import { Construct } from 'constructs';
import { MedyraxStackProps } from '@mdx/types';
import { HipaaCompliantBucket } from '../constructs/data/HipaaCompliantBucket';

// ── Stack-specific props ──────────────────────────────────────────────────────

export interface MedyraxDataStackProps extends MedyraxStackProps {
  /**
   * ARN of the platform-level KMS CMK created by MedyraxSecurityStack.
   * All DynamoDB tables and S3 buckets in this stack are encrypted with it.
   *
   * In a single-account multi-stack deployment, obtain this value from
   * {@code MedyraxSecurityStack.platformCmk.keyArn} and pass it here.
   */
  platformCmkArn: string;
}

// ── DynamoDB table logical names ──────────────────────────────────────────────

/** Logical (construct) IDs for each DynamoDB table created by this stack. */
const TABLE_CONSTRUCT_IDS = {
  fhirIdRegistry: 'FhirIdRegistryTable',
  tenants: 'TenantsTable',
  transformationAudit: 'TransformationAuditTable',
  terminologyCodes: 'TerminologyCodesTable',
  deidentMapping: 'DeidentMappingTable',
  cdsRules: 'CdsRulesTable',
} as const;

// ── Stack ─────────────────────────────────────────────────────────────────────

export class MedyraxDataStack extends cdk.Stack {
  // ── Public constructs / resources exposed for cross-stack references ──

  /** HIPAA-compliant S3 bucket for general platform data (FHIR bulk exports, etc.). */
  public readonly dataBucket: HipaaCompliantBucket;

  /** DynamoDB table: {@code mdx-fhir-id-registry} — FHIR client↔HealthLake ID mapping. */
  public readonly fhirIdRegistryTable: dynamodb.Table;

  /**
   * DynamoDB table: {@code mdx-tenants} — per-org tenant configuration records.
   * PK: orgId, SK: "CONFIG" | "PROFILE#{profileId}"
   */
  public readonly tenantsTable: dynamodb.Table;

  /**
   * DynamoDB table: {@code mdx-transformation-audit} — HL7↔FHIR transformation audit log.
   * PK: orgId#{messageControlId}, SK: timestamp (ISO-8601)
   */
  public readonly transformationAuditTable: dynamodb.Table;

  /**
   * DynamoDB table: {@code mdx-terminology-codes} — LOINC/SNOMED/ICD-10/NPI code cache.
   * PK: {codeSystem}#{code}
   */
  public readonly terminologyCodesTable: dynamodb.Table;

  /**
   * DynamoDB table: {@code mdx-deident-mapping} — encrypted de-identified ID ↔ original FHIR ID.
   * PK: deidentId, SK: orgId
   */
  public readonly deidentMappingTable: dynamodb.Table;

  /**
   * DynamoDB table: {@code mdx-cds-rules} — per-org clinical decision support rules.
   * PK: orgId, SK: ruleId
   */
  public readonly cdsRulesTable: dynamodb.Table;

  /**
   * AWS HealthLake FHIR datastore — one per environment.
   * Created only when {@code envConfig.enableHealthLake = true}; otherwise undefined.
   * Requirement 3.1.
   */
  public readonly healthLakeDataStore?: healthlake.CfnFHIRDatastore;

  constructor(scope: Construct, id: string, props: MedyraxDataStackProps) {
    super(scope, id, props);

    const { envName, envConfig, platformCmkArn } = props;

    // ── Resolve platform CMK ──────────────────────────────────────────────
    // IKey is used for the DynamoDB table encryption; the HipaaCompliantBucket
    // construct receives the ARN string directly.
    const platformCmk = kms.Key.fromKeyArn(this, 'PlatformCmk', platformCmkArn);

    // ── Determine removal policy ──────────────────────────────────────────
    // Retain in staging/prod (HIPAA data retention); destroy in dev.
    const removalPolicy = envConfig.retainStatefulResources
      ? cdk.RemovalPolicy.RETAIN
      : cdk.RemovalPolicy.DESTROY;

    // ═══════════════════════════════════════════════════════════════════════
    // 1. HIPAA-COMPLIANT S3 BUCKET
    //    General-purpose platform data bucket (not org-specific; serves as
    //    HealthLake export destination and transformation-rules store).
    //
    //    Requirements: 7.1, 7.8, 9.7
    // ═══════════════════════════════════════════════════════════════════════
    this.dataBucket = new HipaaCompliantBucket(this, 'PlatformDataBucket', {
      bucketNamePrefix: `mdx-platform-data-${envName}`,
      kmsKeyArn: platformCmkArn,
      versioned: true,
      removalPolicy,
    });

    // ═══════════════════════════════════════════════════════════════════════
    // 2. DYNAMODB TABLES
    //    All tables share:
    //      - Point-in-time recovery (PITR) enabled
    //      - Server-side encryption with the platform CMK
    //      - PAY_PER_REQUEST billing (serverless auto-scaling)
    //      - Removal policy matching envConfig
    //
    //    Requirements: 7.1
    // ═══════════════════════════════════════════════════════════════════════

    // ── 2a. mdx-fhir-id-registry ─────────────────────────────────────────
    // Maps client-submitted FHIR resource IDs to server-generated HealthLake IDs.
    // Design: PK orgId#{fhirResourceType}, SK clientId
    //         GSI1-PK: healthLakeId
    // Requirement 3.1
    this.fhirIdRegistryTable = new dynamodb.Table(
      this,
      TABLE_CONSTRUCT_IDS.fhirIdRegistry,
      {
        tableName: 'mdx-fhir-id-registry',
        partitionKey: {
          name: 'pk',           // orgId#fhirResourceType
          type: dynamodb.AttributeType.STRING,
        },
        sortKey: {
          name: 'sk',           // clientId
          type: dynamodb.AttributeType.STRING,
        },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecovery: true,
        encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
        encryptionKey: platformCmk,
        removalPolicy,
      },
    );

    // GSI for reverse lookup by HealthLake logical ID
    this.fhirIdRegistryTable.addGlobalSecondaryIndex({
      indexName: 'healthLakeId-index',
      partitionKey: {
        name: 'healthLakeId',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ── 2b. mdx-tenants ──────────────────────────────────────────────────
    // Multi-tenant configuration store.
    // Design: PK orgId, SK "CONFIG" | "PROFILE#{profileId}"
    // Requirements 8.1–8.5
    this.tenantsTable = new dynamodb.Table(
      this,
      TABLE_CONSTRUCT_IDS.tenants,
      {
        tableName: 'mdx-tenants',
        partitionKey: {
          name: 'orgId',
          type: dynamodb.AttributeType.STRING,
        },
        sortKey: {
          name: 'sk',           // "CONFIG" or "PROFILE#<id>"
          type: dynamodb.AttributeType.STRING,
        },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecovery: true,
        encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
        encryptionKey: platformCmk,
        // TTL attribute set by the Deprovisioning Lambda (deprovisionedAt + 7 years)
        timeToLiveAttribute: 'ttl',
        removalPolicy,
      },
    );

    // GSI: lookup by tenant status (active | suspended | deprovisioned)
    this.tenantsTable.addGlobalSecondaryIndex({
      indexName: 'status-index',
      partitionKey: {
        name: 'status',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ['orgId', 'orgName', 'provisionedAt'],
    });

    // ── 2c. mdx-transformation-audit ─────────────────────────────────────
    // HL7 ↔ FHIR transformation audit records.
    // Design: PK orgId#{messageControlId}, SK timestamp (ISO-8601)
    //         TTL: timestamp + 7 years (HIPAA retention)
    // Requirement 13.5
    this.transformationAuditTable = new dynamodb.Table(
      this,
      TABLE_CONSTRUCT_IDS.transformationAudit,
      {
        tableName: 'mdx-transformation-audit',
        partitionKey: {
          name: 'pk',           // orgId#messageControlId
          type: dynamodb.AttributeType.STRING,
        },
        sortKey: {
          name: 'timestamp',    // ISO-8601 string (sortable)
          type: dynamodb.AttributeType.STRING,
        },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecovery: true,
        encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
        encryptionKey: platformCmk,
        timeToLiveAttribute: 'ttl',
        removalPolicy,
      },
    );

    // GSI: query all audit records for a given org sorted by time
    this.transformationAuditTable.addGlobalSecondaryIndex({
      indexName: 'orgId-timestamp-index',
      partitionKey: {
        name: 'orgId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ── 2d. mdx-terminology-codes ────────────────────────────────────────
    // Local cache of LOINC, SNOMED CT, ICD-10, and NPI codes.
    // Design: PK {codeSystem}#{code}
    // Requirement 4.1, 4.4
    this.terminologyCodesTable = new dynamodb.Table(
      this,
      TABLE_CONSTRUCT_IDS.terminologyCodes,
      {
        tableName: 'mdx-terminology-codes',
        partitionKey: {
          name: 'pk',           // {codeSystem}#{code}  e.g. LOINC#1234-5
          type: dynamodb.AttributeType.STRING,
        },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecovery: true,
        encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
        encryptionKey: platformCmk,
        // Allow expired entries to be purged automatically
        timeToLiveAttribute: 'ttl',
        removalPolicy,
      },
    );

    // GSI: query all codes for a given code system (e.g. list all LOINC codes)
    this.terminologyCodesTable.addGlobalSecondaryIndex({
      indexName: 'codeSystem-index',
      partitionKey: {
        name: 'codeSystem',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'code',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ── 2e. mdx-deident-mapping ──────────────────────────────────────────
    // Encrypted lookup table: de-identified analytics record ID → original FHIR resource ID.
    // Access restricted to Platform_Admin role only.
    // Requirement 11.4
    this.deidentMappingTable = new dynamodb.Table(
      this,
      TABLE_CONSTRUCT_IDS.deidentMapping,
      {
        tableName: 'mdx-deident-mapping',
        partitionKey: {
          name: 'deidentId',
          type: dynamodb.AttributeType.STRING,
        },
        sortKey: {
          name: 'orgId',
          type: dynamodb.AttributeType.STRING,
        },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecovery: true,
        encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
        encryptionKey: platformCmk,
        removalPolicy,
      },
    );

    // GSI: reverse lookup — find de-identified records for an original FHIR ID
    this.deidentMappingTable.addGlobalSecondaryIndex({
      indexName: 'originalFhirId-index',
      partitionKey: {
        name: 'originalFhirId',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ['deidentId', 'orgId', 'createdAt'],
    });

    // ── 2f. mdx-cds-rules ────────────────────────────────────────────────
    // Per-org Clinical Decision Support rule definitions.
    // Design: PK orgId, SK ruleId
    // Requirement 12.6
    this.cdsRulesTable = new dynamodb.Table(
      this,
      TABLE_CONSTRUCT_IDS.cdsRules,
      {
        tableName: 'mdx-cds-rules',
        partitionKey: {
          name: 'orgId',
          type: dynamodb.AttributeType.STRING,
        },
        sortKey: {
          name: 'ruleId',
          type: dynamodb.AttributeType.STRING,
        },
        billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
        pointInTimeRecovery: true,
        encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
        encryptionKey: platformCmk,
        removalPolicy,
      },
    );

    // GSI: query all enabled rules for a given resource type across all orgs
    this.cdsRulesTable.addGlobalSecondaryIndex({
      indexName: 'triggerResourceType-index',
      partitionKey: {
        name: 'triggerResourceType',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'orgId',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ═══════════════════════════════════════════════════════════════════════
    // 3. AWS HEALTHLAKE FHIR DATASTORE (placeholder, one per environment)
    //
    //    Conditionally created when envConfig.enableHealthLake = true.
    //    In dev, HealthLake provisioning (~20 min) is skipped by default.
    //    Staging and prod set enableHealthLake = true.
    //
    //    This is a "placeholder" configuration: the actual per-org datastores
    //    are created later by the tenant provisioning Step Function
    //    (task 4.2 — tenant-provisioner-healthlake Lambda).  The platform-level
    //    datastore created here serves as the shared dev/staging environment
    //    datastore before per-org provisioning is complete.
    //
    //    Requirement 3.1
    // ═══════════════════════════════════════════════════════════════════════
    if (envConfig.enableHealthLake === true) {
      this.healthLakeDataStore = new healthlake.CfnFHIRDatastore(
        this,
        'PlatformFhirDatastore',
        {
          datastoreTypeVersion: 'R4',
          datastoreName: `mdx-fhir-datastore-${envName}`,
          sseConfiguration: {
            kmsEncryptionConfig: {
              cmkType: 'CUSTOMER_MANAGED_KMS_KEY',
              kmsKeyId: platformCmkArn,
            },
          },
          tags: [
            { key: 'Project', value: 'Medyrax' },
            { key: 'Environment', value: envName },
            { key: 'MdxComponent', value: 'HealthLakeFhirDatastore' },
          ],
        },
      );

      // Emit the datastore ID as a CloudFormation output for use by other stacks
      // and the tenant provisioning Lambda.
      new cdk.CfnOutput(this, 'HealthLakeDataStoreId', {
        value: this.healthLakeDataStore.attrDatastoreId,
        description: `AWS HealthLake FHIR R4 datastore ID for ${envName}`,
        exportName: `mdx-healthlake-datastore-id-${envName}`,
      });

      new cdk.CfnOutput(this, 'HealthLakeDataStoreEndpoint', {
        value: this.healthLakeDataStore.attrDatastoreEndpoint,
        description: `AWS HealthLake FHIR R4 datastore endpoint for ${envName}`,
        exportName: `mdx-healthlake-datastore-endpoint-${envName}`,
      });
    }

    // ── Stack-level tags ──────────────────────────────────────────────────
    cdk.Tags.of(this).add('Project', 'Medyrax');
    cdk.Tags.of(this).add('Layer', 'Data');
    cdk.Tags.of(this).add('Environment', envName);

    // ── CloudFormation outputs ─────────────────────────────────────────────

    new cdk.CfnOutput(this, 'PlatformDataBucketName', {
      value: this.dataBucket.bucketName,
      description: 'Medyrax platform data S3 bucket name',
      exportName: `mdx-platform-data-bucket-${envName}`,
    });

    new cdk.CfnOutput(this, 'FhirIdRegistryTableName', {
      value: this.fhirIdRegistryTable.tableName,
      description: 'DynamoDB table: mdx-fhir-id-registry',
      exportName: `mdx-fhir-id-registry-table-${envName}`,
    });

    new cdk.CfnOutput(this, 'TenantsTableName', {
      value: this.tenantsTable.tableName,
      description: 'DynamoDB table: mdx-tenants',
      exportName: `mdx-tenants-table-${envName}`,
    });

    new cdk.CfnOutput(this, 'TransformationAuditTableName', {
      value: this.transformationAuditTable.tableName,
      description: 'DynamoDB table: mdx-transformation-audit',
      exportName: `mdx-transformation-audit-table-${envName}`,
    });

    new cdk.CfnOutput(this, 'TerminologyCodesTableName', {
      value: this.terminologyCodesTable.tableName,
      description: 'DynamoDB table: mdx-terminology-codes',
      exportName: `mdx-terminology-codes-table-${envName}`,
    });

    new cdk.CfnOutput(this, 'DeidentMappingTableName', {
      value: this.deidentMappingTable.tableName,
      description: 'DynamoDB table: mdx-deident-mapping',
      exportName: `mdx-deident-mapping-table-${envName}`,
    });

    new cdk.CfnOutput(this, 'CdsRulesTableName', {
      value: this.cdsRulesTable.tableName,
      description: 'DynamoDB table: mdx-cds-rules',
      exportName: `mdx-cds-rules-table-${envName}`,
    });
  }
}
