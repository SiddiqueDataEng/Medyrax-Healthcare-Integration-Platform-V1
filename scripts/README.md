# scripts

Utility and automation scripts for the Medyrax™ platform.

## Available Scripts

| Script | Purpose |
|--------|---------|
| `bootstrap.sh` | Bootstrap CDK and create S3 state bucket |
| `seed-terminology.py` | Load initial LOINC / SNOMED CT / ICD-10 / NPI codes into DynamoDB |
| `provision-org.py` | CLI wrapper to provision a new Connected_Organization via the Provisioning API |
| `deprovision-org.py` | CLI wrapper to deprovision a Connected_Organization |
| `rotate-keys.py` | Trigger manual KMS CMK rotation for all orgs |
| `run-localstack.sh` | Start LocalStack with required AWS services for local development |
| `deploy.sh` | Orchestrate full platform deployment (CDK synth → deploy → integration tests) |
| `validate-hipaa.sh` | Run cfn-guard HIPAA policy checks against synthesized CloudFormation templates |

## Usage

```bash
# Bootstrap CDK (run once per AWS account/region)
./bootstrap.sh --account 123456789012 --region us-east-1

# Seed terminology data (requires AWS credentials)
python seed-terminology.py --env dev --source s3://my-terminology-bucket/

# Provision a new org
python provision-org.py \
  --org-id "hospital-abc" \
  --org-name "ABC Medical Center" \
  --env dev
```
