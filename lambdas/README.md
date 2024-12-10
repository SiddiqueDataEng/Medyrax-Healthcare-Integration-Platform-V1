# Medyrax™ Lambda Functions

Python 3.12 data-plane Lambda functions for the Medyrax Healthcare Integration Platform.

> **Deploying?** See the [AWS Deployment Guide](../DEPLOYMENT.md) for complete instructions.
> **Platform overview?** See the [main README](../README.md).

---

## Table of Contents

- [Package Structure](#package-structure)
- [Shared Library (mdx_common)](#shared-library-mdx_common)
- [Lambda Packages](#lambda-packages)
  - [FHIR Engine](#fhir-engine)
  - [HL7 Adapter](#hl7-adapter)
  - [Data Mapper](#mdx-data-mapper)
  - [HealthLake Connector](#healthlake-connector)
  - [Integration Bus](#integration-bus)
  - [Security Layer](#security-layer)
  - [Terminology Validator](#terminology-validator)
  - [Tenant Management](#tenant-management)
  - [File Integration](#file-integration)
  - [Telehealth Connector](#telehealth-connector)
  - [Analytics Connector](#analytics-connector)
  - [CDS (Clinical Decision Support)](#cds)
- [Environment Variables](#environment-variables)
- [Local Development](#local-development)
- [Running Tests](#running-tests)
- [Adding a New Lambda](#adding-a-new-lambda)

---

## Package Structure

```
lambdas/
├── mdx_common/                  # Shared Python package — imported by all Lambdas
│   ├── __init__.py
│   ├── models.py                # EventEnvelope, CanonicalMessage, TenantConfig, AuditLogEntry
│   ├── enums.py                 # FhirResourceType, Hl7MessageType, IntegrationPattern, UserRole
│   ├── errors.py                # MedyraxBaseError and all subsystem-specific exceptions
│   ├── constants.py             # Table/bucket name constants
│   ├── tenant_config_service.py # TenantConfigService — DynamoDB CRUD for tenant config
│   └── tests/                   # 10 property-based test suites (Hypothesis)
│       ├── test_pbt_fhir.py
│       ├── test_pbt_hl7.py
│       ├── test_pbt_security.py
│       ├── test_pbt_healthlake.py
│       ├── test_pbt_integration_bus.py
│       ├── test_pbt_tenant_isolation.py
│       ├── test_pbt_terminology.py
│       ├── test_pbt_telehealth.py
│       ├── test_pbt_file_quarantine.py
│       └── test_pbt_audit_completeness.py
│
├── mdx-data-mapper/             # HL7 ↔ FHIR canonical round-trip engine
│   ├── canonical_to_fhir.py
│   ├── canonical_to_hl7.py
│   ├── fhir_to_canonical.py
│   ├── hl7_to_canonical.py
│   ├── rules_loader.py
│   ├── transformation_auditor.py
│   └── datamapper_diff.py       # POST /v1/admin/mapper/validate
│
├── fhir-engine/                 # FHIR R4 API handlers
│   ├── validate.py              # POST — validate FHIR resource (HTTP 200/422)
│   ├── crud.py                  # POST/PUT/GET/DELETE — all 11 resource types
│   ├── search.py                # GET /{resource}/_search
│   ├── bundle_handler.py        # POST — transaction Bundle (atomic)
│   └── fhir_validator.py        # Validation logic (fhir.resources library)
│
├── hl7-adapter/                 # HL7 v2.x MLLP + file ingestion
│   ├── mllp_listener.py         # NLB TCP 2575 → SQS FIFO (ACK within 200ms)
│   ├── mllp_framing.py          # MLLP byte framing utilities + ACK/NAK builders
│   ├── hl7_parser.py            # SQS trigger → CanonicalMessage
│   ├── hl7_transformer.py       # SQS trigger → FHIR → EventBridge (<2s)
│   └── hl7_file_processor.py    # S3 event → batch HL7 → SQS dispatch
│
├── healthlake-connector/        # AWS HealthLake API integration
│   ├── writer.py                # SQS trigger → CreateResource/UpdateResource (3x retry)
│   ├── reader.py                # GET/search via HealthLake (tenant-isolated)
│   ├── export_trigger.py        # $export → StartFHIRExportJob → SFN
│   └── healthlake_client.py     # HealthLake boto3 wrapper with exponential backoff
│
├── integration-bus/             # EventBridge + SQS Integration Bus
│   ├── integration_bus_publisher.py  # publish_event() utility used by all Lambdas
│   ├── webhook_delivery.py      # SQS poll → HTTP POST (5x backoff: 1-16s)
│   └── filter_config.py         # PUT /v1/integration/filter-config
│
├── security-layer/              # Auth, audit, de-identification
│   ├── audit_logger.py          # CloudWatch PHI audit events + @audit_middleware decorator
│   ├── rbac_middleware.py       # @require_permission decorator + seed_default_permissions()
│   ├── deidentify.py            # HIPAA Safe Harbor — all 18 PHI identifiers
│   └── compliance_report.py    # Daily CloudWatch Logs Insights report
│
├── terminology-validator/       # LOINC / SNOMED CT / ICD-10 / NPI terminology
│   └── handler.py               # GET $validate-code + POST $translate
│
├── tenant-provisioner/          # Provisioning Step Function state handlers
│   ├── validate.py              # State 1: schema validation
│   ├── aws_resources.py         # State 2: KMS/IAM/SQS/EventBridge/S3
│   ├── healthlake.py            # State 3: CreateFHIRDatastore + poll ACTIVE
│   ├── sftp.py                  # State 4: Transfer Family CreateServer
│   └── finalize.py              # State 5: DynamoDB write + SNS welcome
│
├── tenant-provision-api/        # POST/GET /v1/admin/organizations
│   └── handler.py
│
├── tenant-deprovision/          # DELETE /v1/admin/organizations/{orgId}
│   └── handler.py
│
├── file-integration/            # SFTP + S3 file processing
│   ├── file_detector.py         # S3 ObjectCreated → format detection → SQS
│   ├── file_validator.py        # SQS → validate → quarantine on failure
│   ├── file_processor.py        # SQS → dispatch HL7/FHIR records → EventBridge
│   └── file_exporter.py         # EventBridge schedule → HealthLake → NDJSON/HL7 export
│
├── telehealth-connector/        # Telehealth platform integration
│   ├── appointment.py           # POST /telehealth/appointment (<3s)
│   ├── presync.py               # GET /telehealth/patient/{id}/presync (gzip, <2s)
│   ├── resource_router.py       # POST /telehealth/resources → EventBridge (<2s)
│   └── encounter_trigger.py     # EventBridge → start mdx-telehealth-encounter-sfn
│
├── analytics-connector/         # HIPAA-safe analytics pipeline
│   ├── deidentify.py            # SQS → de-identify → Firehose → S3 Parquet
│   ├── everything.py            # GET /Patient/{id}/$everything
│   └── kafka_forwarder.py       # High-priority events → MSK Kafka
│
└── cds/                         # Clinical Decision Support
    ├── cds_hooks_service.py     # GET /cds-services + hook invocations
    └── cds_trigger.py           # EventBridge Observation.created → SFN (<15s)
```

---

## Shared Library (mdx_common)

All Lambda packages import from `mdx_common`. It is deployed as a Lambda Layer in AWS.

### Key modules

**`models.py`** — Core data models:

| Class | Description |
|---|---|
| `EventEnvelope` | Standard event envelope for Integration Bus messages |
| `CanonicalMessage` | Intermediate HL7 ↔ FHIR round-trip representation |
| `TenantConfig` | Runtime org configuration (loaded from DynamoDB) |
| `AuditLogEntry` | PHI access audit record structure |

**`enums.py`** — Platform enumerations:

| Enum | Values |
|---|---|
| `FhirResourceType` | 11 core types + additional (Patient, Encounter, Observation, ...) |
| `Hl7MessageType` | ADT_A01–A40, ORM_O01, ORU_R01, MDM, DFT, SIU, VXU |
| `IntegrationPattern` | fhir_api, hl7_mllp, hl7_file, sftp_file, webhook, ... |
| `UserRole` | Platform_Admin, Organization_Admin, Clinical_User, Integration_Service, Audit_Reviewer |

**`tenant_config_service.py`** — `TenantConfigService`:

```python
from mdx_common.tenant_config_service import get_tenant_config

config = get_tenant_config("acme-hospital")
data_store_id = config.health_lake_data_store_id
kms_key_arn   = config.kms_key_arn
```

---

## Lambda Packages

### FHIR Engine

**Trigger:** API Gateway  
**SLA:** validate 500ms · CRUD 1s · search 2s · bundle atomic

| File | Route | Description |
|---|---|---|
| `validate.py` | `POST /v1/fhir/r4/{resource}` | Validates FHIR R4 resource; returns 200 or 422 OperationOutcome |
| `crud.py` | `POST/PUT/GET/DELETE /v1/fhir/r4/{resource}[/{id}]` | Full CRUD for all 11 resource types |
| `search.py` | `GET /v1/fhir/r4/{resource}/_search` | Translates FHIR search → HealthLake |
| `bundle_handler.py` | `POST /v1/fhir/r4/` | Transaction Bundle; two-phase atomic DynamoDB commit |

### HL7 Adapter

**Trigger:** NLB TCP port 2575 (MLLP) + S3 events  
**SLA:** ACK within 200ms · total transform < 2s

| File | Trigger | Description |
|---|---|---|
| `mllp_listener.py` | NLB → Lambda | Strips MLLP framing; enqueues to SQS FIFO; returns ACK/NAK |
| `mllp_framing.py` | — | `extract_hl7()`, `wrap_hl7()`, `build_ack()`, `build_nak()` |
| `hl7_parser.py` | SQS FIFO | Parses HL7 v2.3–2.8 via `hl7apy`; calls `HL7ToCanonicalParser` |
| `hl7_transformer.py` | SQS | Canonical → FHIR R4; publishes to EventBridge; records audit |
| `hl7_file_processor.py` | S3 ObjectCreated | Splits HL7 batch files; dispatches per-message to SQS |

Supported HL7 message types: `ADT_A01–A13, A28, A29, A31, A40` · `ORM_O01` · `ORU_R01` · `MDM_T01/T02/T11` · `DFT_P03` · `SIU_S12–S15` · `VXU_V04`

### mdx-data-mapper

Bidirectional HL7 ↔ FHIR canonical round-trip engine. Used by HL7 Adapter and FHIR Engine.

| Class / Module | Description |
|---|---|
| `HL7ToCanonicalParser` | hl7apy wrapper; captures unmapped fields in `extension_map` |
| `CanonicalToFHIRSerializer` | Builds FHIR R4 resource dicts from `CanonicalMessage` |
| `FHIRToCanonicalParser` | Parses FHIR R4 JSON into `CanonicalMessage` |
| `CanonicalToHL7Serializer` | Rebuilds HL7 pipe-delimited message from `CanonicalMessage` |
| `TransformationAuditor` | Writes to `mdx-transformation-audit` DynamoDB (7yr TTL) |
| `rules_loader` | `get_ruleset(message_type, version)` — S3-cached ruleset JSON |
| `datamapper_diff.py` | `POST /v1/admin/mapper/validate` — returns JSON diff |

### HealthLake Connector

**Trigger:** SQS (`mdx-{orgId}-healthlake-inbound`) for writer; API GW for reader  
**Retry:** 3 attempts — 1s, 2s, 4s backoff; dead-letter event on exhaustion

| File | Description |
|---|---|
| `writer.py` | CreateResource/UpdateResource; publishes `healthlake.resource.persisted` on success |
| `reader.py` | GetResource/SearchWithGet; enforces `dataStoreId` tenant isolation |
| `export_trigger.py` | `$export` → `StartFHIRExportJob` → starts polling Step Function |
| `healthlake_client.py` | boto3 wrapper with `_is_retriable()` logic and exponential backoff |

### Integration Bus

**Trigger:** SQS webhook queue; API GW for filter config

| File | Description |
|---|---|
| `integration_bus_publisher.py` | `publish_event()` — standard envelope; SQS FIFO MessageGroupId=patientId |
| `webhook_delivery.py` | HTTP POST; 5 retries with 1s/2s/4s/8s/16s backoff |
| `filter_config.py` | `PUT /v1/integration/filter-config` — updates EventBridge rule patterns |

Usage in any Lambda:

```python
from integration_bus.integration_bus_publisher import publish_event

event_id = publish_event(
    org_id="acme-hospital",
    patient_id="patient-abc123",
    resource_type="Observation",
    event_type="fhir.resource.created",
    payload=fhir_observation_dict,
)
```

### Security Layer

| File | Description |
|---|---|
| `audit_logger.py` | `write_audit_event()` + `@audit_middleware` decorator — CWL within 1s |
| `rbac_middleware.py` | `@require_permission("fhir:Patient:read")` decorator — HTTP 403 on denial |
| `deidentify.py` | HIPAA Safe Harbor: removes all 18 PHI identifiers; pure function |
| `compliance_report.py` | Daily EventBridge → CloudWatch Logs Insights → `mdx-compliance-reports` |

Using the audit middleware:

```python
from security_layer.audit_logger import audit_middleware

@audit_middleware(resource_type="Patient", operation="read")
def handler(event, context):
    ...  # audit event written automatically
```

Using the RBAC middleware:

```python
from security_layer.rbac_middleware import require_permission

@require_permission("fhir:Patient:read")
def handler(event, context):
    ...  # returns HTTP 403 if caller lacks the permission
```

### Terminology Validator

**Trigger:** API Gateway  
**SLA:** 300ms

| Route | Description |
|---|---|
| `GET /v1/fhir/r4/CodeSystem/$validate-code?code=X&system=Y` | Validates code; returns Parameters with `result`, `display`, `confidence` |
| `POST /v1/fhir/r4/ConceptMap/$translate` | Maps local code to standard; publishes to `mdx-{orgId}-review-queue` on miss |

Supported systems: `http://loinc.org` · `http://snomed.info/sct` · `http://hl7.org/fhir/sid/icd-10` · `http://hl7.org/fhir/sid/us-npi`

### Tenant Management

| Package | Handler | Route |
|---|---|---|
| `tenant-provision-api` | `handler.py` | `POST /v1/admin/organizations` → triggers SFN (202) |
| `tenant-provision-api` | `handler.py` | `GET /v1/admin/organizations/{orgId}/status` |
| `tenant-deprovision` | `handler.py` | `DELETE /v1/admin/organizations/{orgId}` → revoke + TTL |
| `tenant-provisioner` | `validate.py` | SFN State 1: schema validation |
| `tenant-provisioner` | `aws_resources.py` | SFN State 2: KMS/IAM/SQS/EventBridge/S3 |
| `tenant-provisioner` | `healthlake.py` | SFN State 3: `CreateFHIRDatastore` + poll ACTIVE |
| `tenant-provisioner` | `sftp.py` | SFN State 4: Transfer Family `CreateServer` |
| `tenant-provisioner` | `finalize.py` | SFN State 5: DynamoDB write + SNS welcome |

### File Integration

**Trigger:** S3 ObjectCreated (detector) · SQS (validator, processor) · EventBridge schedule (exporter)

| File | SLA | Description |
|---|---|---|
| `file_detector.py` | 30s | Detects HL7/FHIR NDJSON/CCD by extension + magic bytes |
| `file_validator.py` | 2min/100MB | Validates format; quarantines failures to `mdx-{orgId}-quarantine/` |
| `file_processor.py` | — | Dispatches HL7 messages or FHIR resources to processing queues |
| `file_exporter.py` | Every 30min | Queries `_lastUpdated` → writes `{orgId}/{ts}/{resourceType}.ndjson` |

### Telehealth Connector

**Trigger:** API Gateway (appointment, presync, router) · EventBridge (encounter_trigger)

| File | Route / Trigger | SLA |
|---|---|---|
| `appointment.py` | `POST /telehealth/appointment` | 3s |
| `presync.py` | `GET /telehealth/patient/{id}/presync` | 2s; gzip when `Accept-Encoding: gzip` |
| `resource_router.py` | `POST /telehealth/resources` | 2s; Encounter/Observation only |
| `encounter_trigger.py` | EventBridge `encounter.concluded` | Starts `mdx-telehealth-encounter-sfn` |

### Analytics Connector

**Trigger:** SQS Integration Bus consumer (deidentify) · API GW (everything) · EventBridge (kafka_forwarder)

| File | Description |
|---|---|
| `deidentify.py` | HIPAA de-id → writes `deidentId→originalFhirId` mapping → Kinesis Firehose → S3 Parquet |
| `everything.py` | `GET /Patient/{id}/$everything` — assembles full patient Bundle from HealthLake |
| `kafka_forwarder.py` | High-priority events → MSK Kafka topic `mdx-analytics-{resourceType}` |

S3 output prefix: `s3://mdx-analytics/{resourceType}/{orgId}/{year}/{month}/{day}/`

### CDS

**Trigger:** EventBridge (cds_trigger) · API GW (cds_hooks_service)

| File | Description |
|---|---|
| `cds_hooks_service.py` | Discovery `GET /cds-services`; handles `patient-view`, `order-sign`, `order-select` |
| `cds_trigger.py` | `Observation.created` → evaluate LOINC criticality → start `mdx-cds-sfn` within 15s |

---

## Environment Variables

All Lambdas read configuration from environment variables injected by CDK. Key variables:

| Variable | Default | Description |
|---|---|---|
| `AWS_DEFAULT_REGION` | `us-east-1` | AWS region (injected by Lambda runtime) |
| `MDX_TENANTS_TABLE` | `mdx-tenants` | DynamoDB tenant config table name |
| `MDX_FHIR_ID_REGISTRY_TABLE` | `mdx-fhir-id-registry` | FHIR ID registry table |
| `MDX_TRANSFORMATION_AUDIT_TABLE` | `mdx-transformation-audit` | Audit log table |
| `MDX_TERMINOLOGY_TABLE` | `mdx-terminology-codes` | Terminology code cache table |
| `MDX_RBAC_TABLE` | `mdx-rbac-permissions` | RBAC permissions table |
| `MDX_EVENT_BUS_ARN_TEMPLATE` | `arn:aws:events:{region}:...:event-bus/mdx-{org_id}-bus` | EventBridge bus ARN template |
| `MDX_HL7_INBOUND_QUEUE_URL_TEMPLATE` | `.../mdx-{org_id}-hl7-inbound.fifo` | SQS FIFO queue URL template |
| `MDX_HEALTHLAKE_QUEUE_URL_TEMPLATE` | `.../mdx-{org_id}-healthlake-inbound` | HealthLake SQS queue URL |
| `MDX_SFN_ARN` | — | Provisioning Step Function ARN |
| `MDX_CDS_SFN_ARN` | — | CDS Step Function ARN |
| `MDX_FIREHOSE_STREAM_NAME` | `mdx-analytics-firehose` | Kinesis Firehose stream name |
| `MDX_KAFKA_BOOTSTRAP_SERVERS` | — | MSK bootstrap servers (comma-separated) |
| `MDX_ALERT_SNS_TOPIC_ARN` | — | SNS topic for file validation failure alerts |

---

## Local Development

### Setup

```bash
# From aws/ root
cd lambdas/mdx_common
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt -r requirements-dev.txt
```

### Local Imports

Each Lambda package resolves `mdx_common` via `sys.path.insert`. For local development, ensure you're in the `lambdas/` directory:

```bash
cd aws/lambdas
PYTHONPATH=. python -c "from mdx_common.models import EventEnvelope; print('OK')"
```

### Mocking AWS Services

Use `moto` (already in `requirements-dev.txt`) to mock AWS services in unit tests:

```python
import boto3
from moto import mock_dynamodb

@mock_dynamodb
def test_tenant_config_service():
    # DynamoDB calls are intercepted by moto
    from mdx_common.tenant_config_service import TenantConfigService
    ...
```

---

## Running Tests

### Unit Tests

```bash
cd lambdas/mdx_common
python -m pytest tests/ -v
```

### Property-Based Tests (Hypothesis)

```bash
# Run all PBTs
python -m pytest tests/test_pbt_*.py -v --tb=short

# Run a specific property test suite
python -m pytest tests/test_pbt_security.py -v -x

# Run with increased examples (more thorough)
python -m pytest tests/test_pbt_fhir.py --hypothesis-seed=0 -v
```

### All Tests with Coverage

```bash
python -m pytest tests/ --cov=. --cov-report=term-missing --tb=short
```

### Integration Tests (LocalStack)

Requires Docker:

```bash
cd aws
./scripts/run-integration-tests.sh
```

Or with LocalStack kept running for debugging:

```bash
./scripts/run-integration-tests.sh --no-teardown
```

---

## Adding a New Lambda

1. **Create the package directory:**
   ```bash
   mkdir lambdas/my-new-lambda
   touch lambdas/my-new-lambda/__init__.py
   touch lambdas/my-new-lambda/handler.py
   touch lambdas/my-new-lambda/requirements.txt
   ```

2. **Implement the handler** (`handler.py`):
   ```python
   import sys, os
   sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
   
   from mdx_common.tenant_config_service import get_tenant_config
   from security_layer.audit_logger import audit_middleware
   
   @audit_middleware(resource_type="MyResource", operation="read")
   def handler(event, context):
       org_id = event.get("requestContext", {}).get("authorizer", {}).get("claims", {}).get("custom:orgId", "")
       config = get_tenant_config(org_id)
       return {"statusCode": 200, "body": "{}"}
   ```

3. **Add a CDK Lambda function** in the relevant stack under `medyrax-cdk/src/stacks/`.

4. **Wire to event source** in `medyrax-cdk/src/constructs/wiring/LambdaEventWiring.ts`.

5. **Write property-based tests** in `lambdas/mdx_common/tests/test_pbt_myfeature.py`.

6. **Update this README** to add your Lambda to the appropriate section.

---

## Related Documentation

| Document | Description |
|---|---|
| [../README.md](../README.md) | Platform overview, architecture, API reference |
| [../DEPLOYMENT.md](../DEPLOYMENT.md) | AWS deployment guide — dev, staging, production |
| [../medyrax-cdk/README.md](../medyrax-cdk/README.md) | CDK infrastructure guide |
| [../integration-tests/README.md](../integration-tests/README.md) | LocalStack integration test setup |

---

*Medyrax™ Platform — HIPAA-compliant healthcare integration on AWS*
