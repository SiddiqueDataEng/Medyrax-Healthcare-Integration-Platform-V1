# medyrax-cdk

AWS CDK (TypeScript) infrastructure-as-code for the Medyrax™ healthcare integration platform.

## Structure

```
medyrax-cdk/
  bin/app.ts          CDK app entry point
  src/
    stacks/           CDK stack definitions
    constructs/       Reusable CDK constructs
    types/            Shared TypeScript interfaces
  config/
    dev.json
    staging.json
    prod.json
  test/               CDK snapshot + property tests
```

## Getting Started

```bash
npm install
npm run build
npx cdk synth --context env=dev
```

## Deployment

```bash
npx cdk deploy --context env=dev    # dev environment
npx cdk deploy --context env=staging
npx cdk deploy --context env=prod
```
