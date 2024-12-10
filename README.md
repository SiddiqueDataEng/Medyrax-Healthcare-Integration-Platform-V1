# Medyrax™ Healthcare Integration Platform

> **HIPAA-compliant, multi-tenant healthcare integration platform built on AWS**
> FHIR R4 · HL7 v2.x · AWS CDK v2 · Lambda · HealthLake · EventBridge · SQS

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CDK Version](https://img.shields.io/badge/CDK-v2.144.0-orange)](https://docs.aws.amazon.com/cdk/v2/guide/home.html)
[![FHIR R4](https://img.shields.io/badge/FHIR-R4-green)](https://hl7.org/fhir/R4/)
[![HIPAA](https://img.shields.io/badge/HIPAA-Compliant-red)](https://www.hhs.gov/hipaa)

---

> **Ready to deploy?** See the [**AWS Deployment Guide →**](DEPLOYMENT.md) for complete step-by-step instructions covering dev, staging, and production environments.

---

## Overview

Medyrax is a production-grade **multi-tenant healthcare data integration platform** that enables
hospitals, clinics, and telehealth providers to exchange clinical data using industry-standard
protocols (FHIR R4 and HL7 v2.x) while maintaining full HIPAA compliance.

Key capabilities:

| Capability | Detail |
|---|---|
| **FHIR R4 API** | Full CRUD + search + transaction bundles for 11 resource types |
| **HL7 v2.x Adapter** | MLLP listener + file-based ingestion, versions 2.3 – 2.8 |
| **Data Mapper** | Bidirectional HL7 ↔ FHIR canonical round-trip with audit trail |
| **Multi-Tenancy** | Per-org KMS CMK, SQS queues, EventBridge buses, SFTP endpoints |
| **Terminology Service** | LOINC, SNOMED CT, ICD-10, NPI — Redis cache + DynamoDB store |
| **Analytics Connector** | HIPAA Safe Harbor de-identification → Kinesis Firehose → S3 Parquet |
| **Telehealth Connector** | Appointment sync, pre-visit record push, encounter conclusion SFN |
| **CDS Hooks** | `patient-view`, `order-sign`, `order-select` with FHIRPath rules |
| **Observability** | CloudWatch dashboards, X-Ray tracing, Lambda Powertools structured logging |

---

## Repository Structure

```
aws/
├── medyrax-cdk/              # AWS CDK v2 TypeScript — all infrastructure stacks
│   ├── bin/app.ts            # CDK app entry point
│   ├── src/
│   │   ├── stacks/           # MedyraxSecurityStack, DataStack, CoreStack, ObsStack, TenantStack
│   │   ├── constructs/       # HipaaKmsConstruct, HipaaCompliantBucket, TenantEventBus, ...
│   │   └── types/            # @mdx/types — shared CDK construct props & event envelopes
│   ├── config/
│   │   ├── dev.json
│   │   ├── staging.json
│   │   └── prod.json
│   └── test/                 # CDK snapshot + fast-check property-based tests
│
├── lambdas/                  # All Lambda function packages
│   ├── mdx_common/           # Shared Python package — models, enums, errors, TenantConfigService
│   ├── mdx-common/           # Shared Java/Maven module (canonical data model)
│   ├── mdx-data-mapper/      # HL7 ↔ FHIR canonical round-trip engine
│   ├── fhir-engine/          # FHIR validate / CRUD / search / bundle handler
│   ├── hl7-adapter/          # MLLP listener, parser, transformer, file processor
│   ├── healthlake-connector/ # HealthLake writer, reader, bulk export SFN
│   ├── integration-bus/      # EventBridge publisher, webhook delivery, filter config
│   ├── security-layer/       # Audit logger, RBAC middleware, de-identification, compliance report
│   ├── terminology-service/  # Validator, translator, refresher
│   ├── terminology-validator/# Standalone validator Lambda
│   ├── tenant-provisioner/   # Step Function state handlers (validate, aws, healthlake, sftp, finalize)
│   ├── tenant-provision-api/ # POST /v1/admin/organizations
│   ├── tenant-deprovision/   # DELETE /v1/admin/organizations/{orgId}
│   ├── tenant-management/    # Tenant admin UI backend
│   ├── telehealth-connector/ # Appointment, pre-sync, encounter SFN, resource router
│   ├── analytics-connector/  # De-identify, Firehose writer, Kafka forwarder
│   ├── cds/                  # CDS Hooks service (patient-view, order-sign, order-select)
│   └── file-integration/     # SFTP detector, validator, processor, exporter
│
├── integration-tests/        # Java/Maven LocalStack-based end-to-end tests
│   └── src/                  # Test suites for all integration paths
│
└── scripts/
    ├── build-all.sh          # TypeScript compile + Python wheel + Lambda zip packaging
    └── run-integration-tests.sh  # LocalStack spin-up → test → tear-down
```

---

## Architecture

```
                        ┌─────────────────────────────────────┐
                        │         API Gateway (v1/v2)          │
                        │   Cognito JWT · mTLS · WAF · 1k/min  │
                        └──────────────┬──────────────────────┘
                                       │
           ┌───────────────────────────┼───────────────────────────┐
           │                           │                           │
    ┌──────▼──────┐           ┌────────▼────────┐        ┌────────▼────────┐
    │  FHIR Engine │           │   HL7 Adapter   │        │  Telehealth /   │
    │  validate    │           │  MLLP (port     │        │  CDS / File     │
    │  crud/search │           │  2575) + file   │        │  Integration    │
    │  bundle      │           └────────┬────────┘        └────────┬────────┘
    └──────┬──────┘                     │                           │
           │                    ┌───────▼──────┐                    │
           │                    │  Data Mapper  │                    │
           │                    │  HL7 ↔ FHIR  │                    │
           │                    └───────┬──────┘                    │
           └──────────────────────────┬─┘◄────────────────────────┘
                                      │
                    ┌─────────────────▼──────────────────┐
                    │       Integration Bus               │
                    │  EventBridge (per-org custom bus)   │
                    │  SQS FIFO queues · DLQ · Archive    │
                    └─────────────────┬──────────────────┘
                                      │
           ┌───────────────────────────┼───────────────────────────┐
           │                           │                           │
    ┌──────▼──────┐           ┌────────▼────────┐        ┌────────▼────────┐
    │  HealthLake  │           │   Analytics     │        │   Webhook       │
    │  Connector   │           │  De-identify →  │        │   Delivery      │
    │  FHIR R4     │           │  Firehose → S3  │        │   (HTTP POST)   │
    └─────────────┘           └─────────────────┘        └─────────────────┘
```

---

## CDK Stacks

| Stack | ID | Description |
|---|---|---|
| `MedyraxSecurityStack` | `MDX-Security-{env}` | KMS CMKs, IAM RBAC roles, CloudTrail 7-yr audit |
| `MedyraxDataStack` | `MDX-Data-{env}` | S3 buckets, 6 DynamoDB tables, HealthLake datastore |
| `MedyraxCoreStack` | `MDX-Core-{env}` | API Gateway, Cognito User Pool, base routes |
| `MedyraxObsStack` | `MDX-Obs-{env}` | CloudWatch dashboards, alarms, SNS topics |
| `MedyraxTenantStack` | `MDX-Tenant-{env}` | Org provisioning Step Function (10 states) |

**Deploy order:** Security → Data → Core → Obs → Tenant

---

## DynamoDB Tables

| Table | Purpose | Key |
|---|---|---|
| `mdx-fhir-id-registry` | FHIR client ID ↔ HealthLake logical ID mapping | PK: `orgId#resourceType`, SK: `clientId` |
| `mdx-tenants` | Multi-tenant configuration, integration profiles | PK: `orgId`, SK: `CONFIG\|PROFILE#id` |
| `mdx-transformation-audit` | HL7↔FHIR transform audit log (HIPAA 7yr TTL) | PK: `orgId#msgControlId`, SK: `timestamp` |
| `mdx-terminology-codes` | LOINC / SNOMED CT / ICD-10 / NPI code cache | PK: `{codeSystem}#code` |
| `mdx-deident-mapping` | De-identified analytics ID ↔ original FHIR ID | PK: `deidentId`, SK: `orgId` |
| `mdx-cds-rules` | Per-org CDS rule definitions (FHIRPath conditions) | PK: `orgId`, SK: `ruleId` |

All tables: **PITR enabled · KMS CMK encrypted · PAY_PER_REQUEST**

---

## Lambda Functions

| Function | Runtime | Trigger | SLA |
|---|---|---|---|
| `fhir-engine-validate` | Python 3.12 | API GW | 500ms |
| `fhir-engine-crud` | Python 3.12 | API GW | 1s publish |
| `fhir-engine-search` | Python 3.12 | API GW | 2s |
| `fhir-engine-bundle` | Python 3.12 | API GW | Atomic |
| `hl7-mllp-listener` | Python 3.12 | NLB TCP 2575 | 200ms ACK |
| `hl7-parser` | Python 3.12 | SQS FIFO | — |
| `hl7-transformer` | Python 3.12 | SQS | 2s total |
| `hl7-file-processor` | Python 3.12 | S3 Event | — |
| `healthlake-writer` | Python 3.12 | SQS | 3 retries exp. backoff |
| `healthlake-reader` | Python 3.12 | API GW | 2s |
| `terminology-validator` | Python 3.12 | API GW / internal | 300ms |
| `terminology-translator` | Python 3.12 | API GW / internal | — |
| `terminology-refresher` | Python 3.12 | EventBridge weekly | — |
| `security-audit-logger` | Python 3.12 | Middleware | 1s |
| `security-deidentify` | Python 3.12 | SQS / API header | — |
| `tenant-provisioner-*` | Python 3.12 | Step Functions | 5min total |
| `tenant-deprovision` | Python 3.12 | API GW | Immediate |
| `telehealth-appointment` | Python 3.12 | API GW | 3s |
| `telehealth-presync` | Python 3.12 | API GW | 2s |
| `analytics-deidentify` | Python 3.12 | SQS | — |
| `cds-hooks-service` | Python 3.12 | API GW | — |
| `file-detector` | Python 3.12 | S3 Event | 30s |
| `file-validator` | Python 3.12 | SQS | 2min/100MB |

---

## Getting Started

### Quick Start

```bash
git clone https://github.com/SiddiqueDataEng/Medyrax-Healthcare-Integration-Platform.git
cd Medyrax-Healthcare-Integration-Platform/aws/medyrax-cdk
npm install && npm run build
npx cdk synth --context env=dev
```

For the complete deployment walkthrough — prerequisites, environment configuration, first-time bootstrap, stack deployment, post-deployment setup, and CI/CD — see the:

**[AWS Deployment Guide](DEPLOYMENT.md)**

It covers:
- [Prerequisites & tool versions](DEPLOYMENT.md#1-prerequisites)
- [AWS account preparation & IAM setup](DEPLOYMENT.md#3-aws-account-preparation)
- [Environment configuration (dev / staging / prod)](DEPLOYMENT.md#4-environment-configuration)
- [First-time CDK bootstrap](DEPLOYMENT.md#5-first-time-bootstrap)
- [Deploying all stacks in order](DEPLOYMENT.md#7-deploying-stacks)
- [Provisioning your first organization](DEPLOYMENT.md#9-provisioning-your-first-organization)
- [Verifying the deployment](DEPLOYMENT.md#10-verifying-the-deployment)
- [CI/CD pipeline setup](DEPLOYMENT.md#11-cicd-pipeline-setup)
- [Rollback & troubleshooting](DEPLOYMENT.md#13-rollback-procedure)
- [Cost estimates](DEPLOYMENT.md#16-cost-estimates)

### Prerequisites

- Node.js 20+, Python 3.12+
- AWS CLI v2 configured (`aws configure`)
- CDK CLI: `npm install -g aws-cdk@2.144.0`

### Install & Build

```bash
cd medyrax-cdk
npm install
npm run build

# Synthesize for dev
npx cdk synth --context env=dev
```

### Deploy

```bash
# Bootstrap (first time only per account/region)
npx cdk bootstrap --context env=dev

# Deploy all stacks
npx cdk deploy --context env=dev --all

# Deploy to staging
npx cdk deploy --context env=staging --all --require-approval broadening
```

### Run Tests

```bash
# CDK unit + snapshot + property-based tests
cd medyrax-cdk && npm test

# Python Lambda property-based tests
cd lambdas/mdx_common && python -m pytest tests/ -v

# Full integration test suite (requires Docker)
./scripts/run-integration-tests.sh
```

---

## Security & Compliance

| Control | Implementation |
|---|---|
| **Encryption at rest** | AES-256 via KMS CMK (per-org) on all S3, DynamoDB, SQS |
| **Encryption in transit** | TLS 1.3 enforced; S3 `aws:SecureTransport` bucket policy |
| **Authentication** | OAuth 2.0 JWT (Cognito) — 15-min token expiry |
| **Authorization** | 5-role RBAC (Platform_Admin → Audit_Reviewer) via DynamoDB matrix |
| **Audit logging** | All PHI access logged to CloudWatch `mdx-audit-{orgId}` within 1s |
| **CloudTrail** | 7-year retention in S3 Glacier/Deep Archive |
| **De-identification** | HIPAA Safe Harbor — all 18 PHI identifiers removed/hashed |
| **Tenant isolation** | Per-org KMS CMK, SQS FIFO queues, EventBridge buses |
| **PITR** | Point-in-time recovery enabled on all DynamoDB tables |

---

## Documentation

| Document | Description |
|---|---|
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | Step-by-step AWS deployment guide — dev, staging, production |
| [lambdas/README.md](lambdas/README.md) | Lambda function inventory and local development guide |
| [medyrax-cdk/README.md](medyrax-cdk/README.md) | CDK infrastructure overview |
| [integration-tests/README.md](integration-tests/README.md) | LocalStack integration test setup |
| [scripts/README.md](scripts/README.md) | Build and deployment script reference |

---

## Contributors

| GitHub | Role |
|---|---|
| [@SiddiqueDataEng](https://github.com/SiddiqueDataEng) | Lead Architect & Platform Engineer |
| [@Irfan-SCT](https://github.com/Irfan-SCT) | Major Contributor — CDK Infrastructure & Security Layer |
| [@Farjad-SCT](https://github.com/Farjad-SCT) | Contributor — FHIR Engine & HL7 Adapter |
| [@LOBNA-SCT](https://github.com/LOBNA-SCT) | Contributor — Terminology Service & Analytics |
| [@Saira-SCT](https://github.com/Saira-SCT) | Contributor — Integration Bus & Telehealth Connector |
| [@Usama-SCT](https://github.com/Usama-SCT) | Contributor — Testing & CI/CD |

---

## License

MIT License — see [LICENSE](LICENSE) for details.
