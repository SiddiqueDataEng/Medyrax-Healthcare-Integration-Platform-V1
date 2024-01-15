# integration-tests

End-to-end integration tests for the Medyrax™ platform using LocalStack and pytest.

## Structure

```
integration-tests/
  conftest.py          pytest fixtures — LocalStack clients, tenant setup
  test_fhir_engine.py  FHIR CRUD and Bundle atomicity integration tests
  test_hl7_adapter.py  MLLP and file-based HL7 integration tests
  test_healthlake.py   HealthLake persistence and retrieval tests
  test_security.py     RBAC, audit log, and de-identification tests
  test_integration_bus.py  EventBridge → SQS routing tests
  test_telehealth.py   Telehealth connector end-to-end tests
  test_analytics.py    De-identification pipeline tests
  docker-compose.yml   LocalStack + supporting services
```

## Running Tests

```bash
# Start LocalStack
docker-compose up -d

# Run full integration suite
pytest -v --cov=.

# Run specific test file
pytest test_fhir_engine.py -v
```

## Requirements

- Docker + Docker Compose
- Python 3.12
- LocalStack (community or pro)
- `pip install -r ../lambdas/requirements-dev.txt`
