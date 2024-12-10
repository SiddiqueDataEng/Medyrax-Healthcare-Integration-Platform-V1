# Medyrax™ Platform — AWS Deployment Guide

> Complete step-by-step guide for deploying the Medyrax Healthcare Integration Platform
> to AWS using CDK v2. Covers dev, staging, and production environments.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Repository Setup](#2-repository-setup)
3. [AWS Account Preparation](#3-aws-account-preparation)
4. [Environment Configuration](#4-environment-configuration)
5. [First-Time Bootstrap](#5-first-time-bootstrap)
6. [Building the Platform](#6-building-the-platform)
7. [Deploying Stacks](#7-deploying-stacks)
8. [Post-Deployment Configuration](#8-post-deployment-configuration)
9. [Provisioning Your First Organization](#9-provisioning-your-first-organization)
10. [Verifying the Deployment](#10-verifying-the-deployment)
11. [CI/CD Pipeline Setup](#11-cicd-pipeline-setup)
12. [Upgrading an Environment](#12-upgrading-an-environment)
13. [Rollback Procedure](#13-rollback-procedure)
14. [Destroying an Environment](#14-destroying-an-environment)
15. [Troubleshooting](#15-troubleshooting)
16. [Cost Estimates](#16-cost-estimates)

---

## 1. Prerequisites

### Required Tools

| Tool | Version | Install |
|---|---|---|
| Node.js | 20+ | [nodejs.org](https://nodejs.org) |
| Python | 3.12+ | [python.org](https://python.org) |
| AWS CLI | v2.x | `pip install awscli` or [AWS docs](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) |
| AWS CDK CLI | 2.144.0 | `npm install -g aws-cdk@2.144.0` |
| Docker | 24+ | Required for LocalStack integration tests |
| Maven | 3.9+ | Required only for running Java integration tests |

Verify tool versions:

```bash
node --version        # v20.x.x
python --version      # Python 3.12.x
aws --version         # aws-cli/2.x.x
cdk --version         # 2.144.0
docker --version      # Docker 24.x.x
```

### Required AWS Permissions

The deploying IAM principal needs the following managed policies (or equivalent):
- `AdministratorAccess` — recommended for initial bootstrap
- After bootstrap: a scoped deployment role with CDK permissions is auto-created

### AWS Services Used

Ensure the following services are enabled in your target region:

- AWS Lambda, API Gateway, Cognito, CloudTrail
- AWS KMS, IAM, S3, DynamoDB, SQS, SNS, EventBridge
- AWS HealthLake (us-east-1 only for GA — check availability)
- AWS Transfer Family (SFTP), Kinesis Data Firehose
- AWS Step Functions, CloudWatch, X-Ray
- AWS CodePipeline, CodeBuild (for CI/CD only)

> **HealthLake availability:** AWS HealthLake is available in `us-east-1`, `us-west-2`, and `eu-west-1`. Set `enableHealthLake: false` in `config/dev.json` to skip HealthLake provisioning during development.

---

## 2. Repository Setup

```bash
# Clone the repository
git clone https://github.com/SiddiqueDataEng/Medyrax-Healthcare-Integration-Platform.git
cd Medyrax-Healthcare-Integration-Platform

# Navigate to the AWS platform directory
cd aws

# Install CDK dependencies
cd medyrax-cdk
npm install

# Verify the build compiles
npm run build
```

Install Python development dependencies:

```bash
cd ../lambdas/mdx_common
pip install -r requirements.txt -r requirements-dev.txt
```

---

## 3. AWS Account Preparation

### 3.1 Configure AWS CLI Profile

```bash
# Configure default profile
aws configure

# Or configure a named profile (recommended for multi-account)
aws configure --profile medyrax-dev
export AWS_PROFILE=medyrax-dev
```

You will need:
- AWS Access Key ID
- AWS Secret Access Key
- Default region (e.g. `us-east-1`)
- Default output format: `json`

### 3.2 Verify Access

```bash
aws sts get-caller-identity
```

Expected output:
```json
{
  "UserId": "AIDA...",
  "Account": "123456789012",
  "Arn": "arn:aws:iam::123456789012:user/deploy-user"
}
```

### 3.3 Create Deployment Role (Recommended for CI/CD)

For automated deployments, create a dedicated IAM role instead of using your personal credentials:

```bash
# Create deployment role
aws iam create-role \
  --role-name MedyraxDeployRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "codebuild.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach necessary policies
aws iam attach-role-policy \
  --role-name MedyraxDeployRole \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
```

---

## 4. Environment Configuration

All environment-specific values live in `medyrax-cdk/config/`. Three environments are provided:

```
medyrax-cdk/config/
  dev.json        # Development — minimal services, fast iteration
  staging.json    # Staging — production-like, approval gates
  prod.json       # Production — full HA, HIPAA retention policies
```

### 4.1 Edit dev.json

```bash
cd medyrax-cdk
nano config/dev.json
```

```json
{
  "_comment": "Medyrax DEV environment — fill in your AWS account details",
  "awsAccountId": "YOUR_AWS_ACCOUNT_ID",
  "awsRegion": "us-east-1",
  "envName": "dev",
  "enableWaf": false,
  "enableHealthLake": false,
  "enableMsk": false,
  "enableElastiCache": false,
  "retainTables": false,
  "cognitoAccessTokenExpiryMinutes": 15,
  "enableXRay": true,
  "mllpPort": 2575
}
```

> Set `enableHealthLake: true` only in staging/prod — HealthLake provisioning takes ~20 minutes.

### 4.2 Edit staging.json

```json
{
  "awsAccountId": "YOUR_AWS_ACCOUNT_ID",
  "awsRegion": "us-east-1",
  "envName": "staging",
  "enableWaf": true,
  "enableHealthLake": true,
  "enableMsk": false,
  "enableElastiCache": true,
  "retainTables": true,
  "cognitoAccessTokenExpiryMinutes": 15,
  "enableXRay": true,
  "mllpPort": 2575,
  "vpcId": "vpc-XXXXXXXXXXXXXXXXX",
  "privateSubnetIds": ["subnet-XXXXXXXXXXXXXXXXX", "subnet-YYYYYYYYYYYYYYYYY"],
  "publicSubnetIds": ["subnet-AAAAAAAAAAAAAAAAAA", "subnet-BBBBBBBBBBBBBBBBBB"],
  "apiDomainName": "api-staging.your-domain.com",
  "apiCertificateArn": "arn:aws:acm:us-east-1:ACCOUNT:certificate/CERT-ID",
  "pagerDutySnsTopicArn": "arn:aws:sns:us-east-1:ACCOUNT:PagerDuty-Critical"
}
```

### 4.3 Edit prod.json

```json
{
  "awsAccountId": "YOUR_PROD_AWS_ACCOUNT_ID",
  "awsRegion": "us-east-1",
  "envName": "prod",
  "enableWaf": true,
  "enableHealthLake": true,
  "enableMsk": true,
  "enableElastiCache": true,
  "retainTables": true,
  "cognitoAccessTokenExpiryMinutes": 15,
  "enableXRay": true,
  "mllpPort": 2575,
  "vpcId": "vpc-PROD-XXXXXXXXXXXXXXXXX",
  "privateSubnetIds": ["subnet-PROD-1", "subnet-PROD-2", "subnet-PROD-3"],
  "publicSubnetIds": ["subnet-PROD-PUB-1", "subnet-PROD-PUB-2"],
  "apiDomainName": "api.your-domain.com",
  "apiCertificateArn": "arn:aws:acm:us-east-1:PROD_ACCOUNT:certificate/PROD-CERT-ID",
  "pagerDutySnsTopicArn": "arn:aws:sns:us-east-1:PROD_ACCOUNT:PagerDuty-Critical"
}
```

---

## 5. First-Time Bootstrap

CDK bootstrap creates the S3 bucket and IAM roles needed for CDK deployments. **Run once per account/region.**

```bash
cd medyrax-cdk

# Bootstrap dev account
npx cdk bootstrap \
  aws://YOUR_AWS_ACCOUNT_ID/us-east-1 \
  --context env=dev \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess

# Bootstrap staging (if separate account)
npx cdk bootstrap \
  aws://YOUR_STAGING_ACCOUNT_ID/us-east-1 \
  --context env=staging \
  --trust YOUR_TOOLCHAIN_ACCOUNT_ID

# Bootstrap prod
npx cdk bootstrap \
  aws://YOUR_PROD_ACCOUNT_ID/us-east-1 \
  --context env=prod \
  --trust YOUR_TOOLCHAIN_ACCOUNT_ID
```

Verify bootstrap succeeded:

```bash
aws cloudformation describe-stacks \
  --stack-name CDKToolkit \
  --query "Stacks[0].StackStatus"
# Expected: "CREATE_COMPLETE" or "UPDATE_COMPLETE"
```

---

## 6. Building the Platform

### 6.1 Compile TypeScript

```bash
cd medyrax-cdk
npm run build
```

### 6.2 Run Tests Before Deploying

```bash
# CDK snapshot and property-based tests
npm test

# Python property-based tests
cd ../lambdas/mdx_common
python -m pytest tests/ -v --tb=short
```

All tests should pass before deploying.

### 6.3 Full Build Script

Use the provided build script to compile everything at once:

```bash
cd aws
./scripts/build-all.sh dev
```

This script:
1. Compiles TypeScript (both CDK projects)
2. Packages Python Lambda layers as wheels
3. Creates Lambda zip artifacts in `dist/lambdas/`
4. Runs `cdk synth` to validate all stacks

### 6.4 Synthesize CloudFormation Templates

```bash
cd medyrax-cdk
npx cdk synth --context env=dev
```

Review the generated templates in `cdk.out/`:
- `MedyraxSecurityStack-dev.template.json`
- `MedyraxDataStack-dev.template.json`
- `MedyraxCoreStack-dev.template.json`
- `MedyraxObsStack-dev.template.json`
- `MedyraxTenantStack-dev.template.json`

### 6.5 Run cfn-guard Compliance Validation

```bash
# Install cfn-guard (Rust-based tool)
cargo install cfn-guard   # or use the pre-built binary

# Validate all synthesized templates
for template in cdk.out/*.template.json; do
  echo "Validating $template..."
  cfn-guard validate \
    --data "$template" \
    --rules cfn-guard/hipaa_rules.guard \
    --show-summary pass,fail
done
```

All templates must show **0 violations** before deploying to staging or production.

---

## 7. Deploying Stacks

### 7.1 Stack Deployment Order

Stacks must be deployed in dependency order:

```
1. MedyraxSecurityStack   (KMS, IAM, CloudTrail)
2. MedyraxDataStack       (S3, DynamoDB, HealthLake) — depends on Security
3. MedyraxCoreStack       (API Gateway, Cognito)     — depends on Security + Data
4. MedyraxObsStack        (CloudWatch, alarms)       — depends on Core
5. MedyraxTenantStack     (Step Function, tenant SFN) — depends on Data + Security
```

### 7.2 Deploy to Dev

```bash
cd medyrax-cdk

# Deploy all stacks at once (CDK handles dependency order)
npx cdk deploy --context env=dev --all

# Or deploy one at a time for better visibility
npx cdk deploy MedyraxSecurityStack-dev --context env=dev
npx cdk deploy MedyraxDataStack-dev     --context env=dev
npx cdk deploy MedyraxCoreStack-dev     --context env=dev
npx cdk deploy MedyraxObsStack-dev      --context env=dev
npx cdk deploy MedyraxTenantStack-dev   --context env=dev
```

Expected deploy time: **8–12 minutes** (dev, HealthLake disabled).

### 7.3 Deploy to Staging

```bash
npx cdk deploy \
  --context env=staging \
  --all \
  --require-approval broadening
```

> `--require-approval broadening` prompts for approval only when IAM or security group rules are broadened.

Expected deploy time: **25–35 minutes** (staging, HealthLake enabled).

### 7.4 Deploy to Production

```bash
npx cdk deploy \
  --context env=prod \
  --all \
  --require-approval any
```

> `--require-approval any` prompts for approval on every security-relevant change.

Expected deploy time: **30–45 minutes** (prod, all services enabled).

### 7.5 Viewing Diff Before Deploy

Always review what will change before deploying to staging or prod:

```bash
npx cdk diff --context env=staging --all
```

### 7.6 Capture Stack Outputs

After deployment, CDK prints stack outputs. Save these for configuration:

```bash
# Get all outputs for a specific stack
aws cloudformation describe-stacks \
  --stack-name medyrax-core-dev \
  --query "Stacks[0].Outputs" \
  --output table
```

Key outputs to note:

| Output Key | Description |
|---|---|
| `ApiEndpoint` | API Gateway base URL |
| `UserPoolId` | Cognito User Pool ID |
| `UserPoolArn` | Cognito User Pool ARN |
| `PlatformCmkArn` | Platform KMS CMK ARN |
| `AuditBucketName` | CloudTrail audit S3 bucket |
| `ProvisioningStateMachineArn` | Tenant provisioning Step Function ARN |

---

## 8. Post-Deployment Configuration

### 8.1 Create Cognito Users

```bash
# Set variables from stack outputs
USER_POOL_ID="us-east-1_XXXXXXXXX"

# Create Platform_Admin user
aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username admin@your-domain.com \
  --user-attributes \
    Name=email,Value=admin@your-domain.com \
    Name=custom:orgId,Value=platform \
  --temporary-password "TempPass123!" \
  --message-action SUPPRESS

# Add user to Platform_Admin group
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$USER_POOL_ID" \
  --username admin@your-domain.com \
  --group-name Platform_Admin
```

### 8.2 Create Cognito Groups

```bash
for role in Platform_Admin Organization_Admin Clinical_User Integration_Service Audit_Reviewer; do
  aws cognito-idp create-group \
    --user-pool-id "$USER_POOL_ID" \
    --group-name "$role" \
    --description "Medyrax RBAC role: $role"
  echo "Created group: $role"
done
```

### 8.3 Seed RBAC Permissions Table

```bash
cd lambdas/security-layer
python - <<'EOF'
import os
os.environ["MDX_RBAC_TABLE"] = "mdx-rbac-permissions"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
from rbac_middleware import seed_default_permissions
seed_default_permissions()
print("RBAC permissions seeded successfully")
EOF
```

### 8.4 Configure Custom Domain (Optional)

```bash
# Get the API Gateway domain name from CloudFormation outputs
API_GW_DOMAIN=$(aws cloudformation describe-stacks \
  --stack-name medyrax-core-staging \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text)

# Create Route 53 alias record
aws route53 change-resource-record-sets \
  --hosted-zone-id "YOUR_HOSTED_ZONE_ID" \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "api-staging.your-domain.com",
        "Type": "A",
        "AliasTarget": {
          "DNSName": "'"$API_GW_DOMAIN"'",
          "EvaluateTargetHealth": false,
          "HostedZoneId": "Z1UJRXOUMOOFQ8"
        }
      }
    }]
  }'
```

### 8.5 Load Terminology Codes (Initial Seed)

For the Terminology Service to function, load initial LOINC/SNOMED/ICD-10 codes:

```bash
# Download and load LOINC codes (requires LOINC license)
# Place loinc.csv in s3://mdx-terminology-snapshots-ACCOUNT-dev/loinc/

# Trigger the terminology refresher Lambda manually
aws lambda invoke \
  --function-name mdx-terminology-refresher-dev \
  --payload '{"force": true}' \
  /tmp/refresh-output.json

cat /tmp/refresh-output.json
```

### 8.6 Configure MLLP Endpoint (HL7 TCP)

The NLB for MLLP is provisioned by the CDK. Point your HL7 sender to:

```
Host: <NLB-DNS-Name>   # from CloudFormation outputs NlbDnsName
Port: 2575             # configurable via mllpPort in config/*.json
Protocol: TCP
```

Get the NLB DNS name:

```bash
aws elbv2 describe-load-balancers \
  --query "LoadBalancers[?contains(LoadBalancerName,'mdx')].DNSName" \
  --output text
```

---

## 9. Provisioning Your First Organization

### 9.1 Get an Access Token

```bash
# Set Cognito app client details from stack outputs
CLIENT_ID="your-cognito-client-id"
USER_POOL_ID="us-east-1_XXXXXXXXX"

# Authenticate and get tokens
TOKEN_RESPONSE=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=admin@your-domain.com,PASSWORD="YourPassword123!" \
  --client-id "$CLIENT_ID")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | python -c "import sys,json; print(json.load(sys.stdin)['AuthenticationResult']['AccessToken'])")
```

### 9.2 Create a New Organization

```bash
API_BASE="https://your-api-id.execute-api.us-east-1.amazonaws.com/v1"

# POST /v1/admin/organizations
curl -X POST "$API_BASE/admin/organizations" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "orgId": "acme-hospital",
    "orgName": "ACME Memorial Hospital",
    "adminEmail": "it-admin@acme-hospital.org",
    "integrationProfile": "HL7_FHIR",
    "region": "us-east-1"
  }'
```

Response (202 Accepted):
```json
{
  "orgId": "acme-hospital",
  "executionArn": "arn:aws:states:us-east-1:123:execution:mdx-org-provision-sfn:provision-acme-hospital",
  "status": "PROVISIONING_STARTED",
  "message": "Provisioning workflow started for org 'acme-hospital'."
}
```

### 9.3 Poll Provisioning Status

```bash
# Poll until status = PROVISIONING_COMPLETE (takes ~3-5 minutes)
while true; do
  STATUS=$(curl -s "$API_BASE/admin/organizations/acme-hospital/status" \
    -H "Authorization: Bearer $ACCESS_TOKEN" | python -c "import sys,json; print(json.load(sys.stdin).get('status','?'))")
  echo "Status: $STATUS"
  [[ "$STATUS" == "PROVISIONING_COMPLETE" ]] && break
  [[ "$STATUS" == "PROVISIONING_FAILED" ]] && echo "FAILED" && break
  sleep 10
done
```

### 9.4 Test the Provisioned Organization

```bash
# Create a FHIR Patient resource for the new org
curl -X POST "$API_BASE/fhir/r4/Patient" \
  -H "Authorization: Bearer $ORG_ACCESS_TOKEN" \
  -H "Content-Type: application/fhir+json" \
  -d '{
    "resourceType": "Patient",
    "name": [{"family": "Doe", "given": ["John"]}],
    "birthDate": "1980-01-15",
    "gender": "male"
  }'
```

---

## 10. Verifying the Deployment

### 10.1 Health Check Endpoints

```bash
API_BASE="https://your-api-id.execute-api.us-east-1.amazonaws.com/v1"

# FHIR CapabilityStatement (no auth required)
curl -s "$API_BASE/fhir/r4/metadata" | python -m json.tool | head -20

# CDS Hooks discovery (no auth required)
curl -s "$API_BASE/cds-services" | python -m json.tool
```

### 10.2 Run Integration Tests Against Live Environment

```bash
cd aws
export AWS_DEFAULT_REGION=us-east-1
export MDX_API_BASE_URL="https://your-api-id.execute-api.us-east-1.amazonaws.com/v1"

./scripts/run-integration-tests.sh
```

### 10.3 Verify CloudWatch Dashboard

Open the Medyrax Integration Health dashboard:

```bash
aws cloudwatch get-dashboard \
  --dashboard-name "Medyrax-Integration-Health-dev" \
  --query "DashboardBody" \
  --output text | python -m json.tool | head -30
```

Or visit directly in the Console:
`https://console.aws.amazon.com/cloudwatch/home#dashboards:name=Medyrax-Integration-Health-dev`

### 10.4 Verify CloudTrail is Active

```bash
aws cloudtrail get-trail-status \
  --name mdx-audit-trail-dev \
  --query "{IsLogging: IsLogging, LatestDeliveryTime: LatestDeliveryTime}"
```

Expected: `"IsLogging": true`

### 10.5 Verify DynamoDB Tables

```bash
for table in mdx-fhir-id-registry mdx-tenants mdx-transformation-audit \
             mdx-terminology-codes mdx-deident-mapping mdx-cds-rules; do
  STATUS=$(aws dynamodb describe-table --table-name "$table" \
    --query "Table.TableStatus" --output text 2>/dev/null || echo "NOT FOUND")
  echo "$table: $STATUS"
done
```

All tables should show: `ACTIVE`

### 10.6 Verify FHIR Validation

```bash
# Valid Patient — should return 200
curl -s -X POST "$API_BASE/fhir/r4/Patient" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/fhir+json" \
  -d '{"resourceType":"Patient","id":"test-001","name":[{"family":"Test"}]}' \
  -w "\nHTTP %{http_code}\n"

# Invalid resource — should return 422 OperationOutcome
curl -s -X POST "$API_BASE/fhir/r4/Patient" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/fhir+json" \
  -d '{"notAFhirResource":true}' \
  -w "\nHTTP %{http_code}\n"
```

---

## 11. CI/CD Pipeline Setup

### 11.1 Deploy the CI/CD Stack

The `MedyraxCicdStack` creates a CodePipeline for automated deployments.

First, create a CodeStar connection to your GitHub repository:

```bash
# Create GitHub connection
aws codestar-connections create-connection \
  --provider-type GitHub \
  --connection-name medyrax-github \
  --query "ConnectionArn" \
  --output text
```

> After creating, you must **activate** the connection in the AWS Console:
> CodePipeline → Settings → Connections → Activate Pending

Then deploy the CI/CD stack:

```bash
cd medyrax-cdk

# Edit bin/app.ts to add MedyraxCicdStack instantiation (or use CDK context)
npx cdk deploy MedyraxCicdStack-dev \
  --context env=dev \
  --context githubConnectionArn="arn:aws:codestar-connections:us-east-1:ACCOUNT:connection/UUID" \
  --context repoOwner="SiddiqueDataEng" \
  --context repoName="Medyrax-Healthcare-Integration-Platform"
```

### 11.2 Pipeline Stages

The pipeline runs automatically on every push to the configured branch:

```
Source (GitHub)
    ↓
Build + Test + Synth (CodeBuild ~8 min)
    ├── npm run lint
    ├── npm test (CDK snapshot + fast-check PBTs)
    ├── python -m pytest (Hypothesis PBTs)
    └── cdk synth --context env=dev
    ↓
Deploy Dev (CDK deploy ~12 min)
    ↓
[Manual Approval for Staging]
    ↓
Deploy Staging (~30 min)
    ↓
[Manual Approval for Production]
    ↓
Deploy Production (~40 min)
```

### 11.3 Triggering a Manual Deploy

```bash
# Trigger pipeline manually
aws codepipeline start-pipeline-execution \
  --name medyrax-pipeline-dev

# Watch pipeline execution
aws codepipeline get-pipeline-execution \
  --pipeline-name medyrax-pipeline-dev \
  --pipeline-execution-id EXECUTION_ID \
  --query "pipelineExecution.status"
```

---

## 12. Upgrading an Environment

### 12.1 Review What Will Change

```bash
cd medyrax-cdk
npx cdk diff --context env=dev --all
```

Pay special attention to:
- `[-]` lines — resources being **removed** (potentially destructive)
- IAM policy changes
- KMS key changes (never delete KMS keys with active data)
- DynamoDB changes (schema changes require table recreation)

### 12.2 Apply Upgrade

```bash
# Dev — no approval needed
npx cdk deploy --context env=dev --all

# Staging — approval required for security changes
npx cdk deploy --context env=staging --all --require-approval broadening

# Prod — approval required for any change
npx cdk deploy --context env=prod --all --require-approval any
```

### 12.3 Lambda-Only Updates (Fast Path)

For Lambda code-only updates (no infrastructure changes):

```bash
# Build Lambda zip
cd aws
./scripts/build-all.sh dev

# Update specific Lambda function directly
aws lambda update-function-code \
  --function-name mdx-fhir-engine-validate-dev \
  --zip-file fileb://dist/lambdas/fhir-engine.zip

# Or use CDK for all Lambdas
cd medyrax-cdk
npx cdk deploy MedyraxCoreStack-dev --context env=dev
```

---

## 13. Rollback Procedure

### 13.1 CDK Rollback via CloudFormation

CloudFormation automatically rolls back on deployment failure. To manually trigger rollback:

```bash
# Roll back a specific stack to its last stable state
aws cloudformation cancel-update-stack \
  --stack-name medyrax-core-dev

# Or roll back to a specific previous deployment
aws cloudformation continue-update-rollback \
  --stack-name medyrax-core-dev
```

### 13.2 Lambda Alias Rollback

If using Lambda versioning with `live` alias:

```bash
# Get the previous version number
aws lambda list-versions-by-function \
  --function-name mdx-fhir-engine-validate-dev \
  --query "Versions[-2].Version" \
  --output text

# Immediately point 'live' alias to previous version
aws lambda update-alias \
  --function-name mdx-fhir-engine-validate-dev \
  --name live \
  --function-version PREVIOUS_VERSION_NUMBER
```

### 13.3 Emergency API Disable

To immediately stop all API traffic during an incident:

```bash
# Disable API Gateway stage
aws apigateway update-stage \
  --rest-api-id YOUR_API_ID \
  --stage-name v1 \
  --patch-operations op=replace,path=/throttlingRateLimit,value=0
```

Re-enable by setting throttlingRateLimit back to 1000.

---

## 14. Destroying an Environment

> **WARNING:** This is irreversible for production environments. Never destroy prod without explicit authorization.

### 14.1 Destroy Dev Environment

```bash
cd medyrax-cdk

# Preview what will be destroyed
npx cdk diff --context env=dev

# Destroy all stacks (reverse dependency order)
npx cdk destroy \
  MedyraxTenantStack-dev \
  MedyraxObsStack-dev \
  MedyraxCoreStack-dev \
  MedyraxDataStack-dev \
  MedyraxSecurityStack-dev \
  --context env=dev \
  --force
```

> DynamoDB tables with `retainTables: true` (staging/prod) will **not** be deleted by CDK. Delete them manually if needed:
> ```bash
> aws dynamodb delete-table --table-name mdx-tenants
> ```

### 14.2 Clean Up S3 Buckets

CDK cannot delete non-empty S3 buckets. Empty them first:

```bash
# Empty audit trail bucket
aws s3 rm s3://mdx-audit-trail-ACCOUNT-dev --recursive

# CDK will then delete it on the next destroy
```

---

## 15. Troubleshooting

### CloudFormation Stack in ROLLBACK_COMPLETE

```bash
# Delete the failed stack and redeploy
aws cloudformation delete-stack --stack-name medyrax-data-dev
# Wait for deletion...
npx cdk deploy MedyraxDataStack-dev --context env=dev
```

### CDK Bootstrap Mismatch

```bash
# Re-bootstrap the account
npx cdk bootstrap aws://ACCOUNT_ID/REGION \
  --context env=dev \
  --cloudformation-execution-policies arn:aws:iam::aws:policy/AdministratorAccess
```

### Lambda Timeout / Memory Error

Increase Lambda memory or timeout in the CDK stack. Common adjustments:

```typescript
// In the relevant CDK stack or Lambda construct
const fn = new lambda.Function(this, 'MyFn', {
  memorySize: 1024,          // increase from default 512MB
  timeout: cdk.Duration.seconds(60),  // increase from default 30s
});
```

### HealthLake Provisioning Timeout

HealthLake CreateFHIRDatastore takes up to 20 minutes. If the tenant provisioning Step Function times out:

```bash
# Check HealthLake datastore status
aws healthlake list-fhir-datastores \
  --query "DatastorePropertiesList[*].{Name:DatastoreName,Status:DatastoreStatus}"
```

If stuck in `CREATING`, wait and re-run the provisioning Step Function execution.

### DynamoDB Table Already Exists

If you get `ResourceInUseException` for DynamoDB tables:

```bash
# Import existing table into CDK
# Or delete and redeploy
aws dynamodb delete-table --table-name mdx-tenants
npx cdk deploy MedyraxDataStack-dev --context env=dev
```

### API Gateway 403 on FHIR Endpoints

Ensure your Cognito token has the correct claims:

```bash
# Decode JWT to inspect claims
echo "YOUR_ACCESS_TOKEN" | python -c "
import sys, base64, json
token = sys.stdin.read().strip()
parts = token.split('.')
payload = base64.b64decode(parts[1] + '==')
print(json.dumps(json.loads(payload), indent=2))
"
```

Required claims: `sub`, `custom:orgId`, `cognito:groups`.

### SQS FIFO Queue Name Conflict

FIFO queue names must end in `.fifo`. If deployment fails on queue creation:

```bash
# Check existing queues
aws sqs list-queues --queue-name-prefix mdx-

# Delete conflicting queue (loses in-flight messages!)
aws sqs delete-queue --queue-url "https://sqs.us-east-1.amazonaws.com/ACCOUNT/QUEUE_NAME"
```

---

## 16. Cost Estimates

Monthly cost estimates for the Medyrax platform (us-east-1, approximate):

### Development Environment

| Service | Usage | Est. Monthly Cost |
|---|---|---|
| Lambda | 1M invocations, 512MB, 3s avg | ~$2 |
| API Gateway | 1M requests | ~$4 |
| DynamoDB | 6 tables, PAY_PER_REQUEST, low traffic | ~$5 |
| S3 | Audit trail + data buckets, 10GB | ~$2 |
| KMS | 1 CMK + API calls | ~$2 |
| CloudWatch | Logs, metrics, alarms | ~$5 |
| SQS | 1M messages | ~$0.40 |
| EventBridge | 1M events | ~$1 |
| **Dev Total** | | **~$21/month** |

### Staging Environment

| Service | Est. Monthly Cost |
|---|---|
| Lambda (higher traffic) | ~$15 |
| API Gateway | ~$20 |
| DynamoDB | ~$25 |
| HealthLake | ~$200 (based on data volume) |
| ElastiCache (t3.micro) | ~$15 |
| Transfer Family SFTP | ~$10/endpoint |
| S3, KMS, CloudWatch, SQS | ~$30 |
| **Staging Total** | **~$315/month** |

### Production Environment

Production costs depend heavily on message volume and data stored in HealthLake. Estimated range: **$800–$3,000/month** for a mid-sized healthcare organization (100k FHIR transactions/day).

> **Cost optimization tips:**
> - Set `enableHealthLake: false` in dev — saves ~$200/month
> - Use `PAY_PER_REQUEST` DynamoDB (already configured) for variable workloads
> - Enable S3 Intelligent-Tiering for long-lived audit data
> - Right-size Lambda memory based on CloudWatch Lambda Insights data

---

## Related Documentation

| Document | Description |
|---|---|
| [README.md](README.md) | Platform overview, architecture, API reference |
| [lambdas/README.md](lambdas/README.md) | Lambda function inventory and development guide |
| [medyrax-cdk/README.md](medyrax-cdk/README.md) | CDK infrastructure guide |
| [integration-tests/README.md](integration-tests/README.md) | LocalStack integration test setup |
| [scripts/README.md](scripts/README.md) | Build and deployment script reference |

---

*Medyrax™ Platform — HIPAA-compliant healthcare integration on AWS*
*For support: [GitHub Issues](https://github.com/SiddiqueDataEng/Medyrax-Healthcare-Integration-Platform/issues)*
