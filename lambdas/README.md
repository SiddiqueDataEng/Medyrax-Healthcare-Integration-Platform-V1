# lambdas

Python 3.12 Lambda functions for the Medyrax™ platform data plane.

## Structure

```
lambdas/
  mdx_common/          Shared Python package (models, enums, errors, constants)
  fhir-engine/         FHIR R4 validation, CRUD, search, bundle handler
  hl7-adapter/         MLLP listener, parser, transformer, file processor
  healthlake-connector/HealthLake writer, reader, bulk export
  terminology-service/ Code validation and translation
  integration-bus/     Webhook delivery, event filter config
  security-layer/      Audit logger, RBAC middleware, de-identification
  data-mapper/         Canonical model, HL7↔FHIR round-trip
  analytics-connector/ De-identification, Firehose, Kafka forwarder
  telehealth-connector/Appointment, pre-sync, encounter conclusion
  cds/                 Clinical decision support, rule evaluator
  tenant-management/   Provisioning and deprovisioning Lambdas
  file-integration/    File detector, validator, processor, exporter
  requirements.txt     Production dependencies
  requirements-dev.txt Development / test dependencies
```

## Getting Started

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
```
