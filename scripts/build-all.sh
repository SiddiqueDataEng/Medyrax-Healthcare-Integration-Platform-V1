#!/usr/bin/env bash
# =============================================================================
# build-all.sh — Builds the entire Medyrax™ platform
#
# Usage:
#   ./scripts/build-all.sh [dev|staging|prod]
#
# Steps:
#   1. Build all Java Lambda modules (Maven multi-module)
#   2. Build and test CDK TypeScript infrastructure
#   3. Run CDK synth for the target environment
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV="${1:-dev}"

echo "=== Medyrax™ Platform Build ==="
echo "Environment: $ENV"
echo "Repo root:   $REPO_ROOT"
echo ""

# ── 1. Java Lambda build ─────────────────────────────────────────────────────
echo "--- Building Java Lambda modules ---"
cd "$REPO_ROOT"
mvn clean package -DskipTests=false -T 4 2>&1

echo "--- Java build complete ---"
echo ""

# ── 2. CDK TypeScript build ───────────────────────────────────────────────────
echo "--- Building CDK TypeScript infrastructure ---"
cd "$REPO_ROOT/Medyrax-cdk"

if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm ci
fi

npm run build
npm test

echo "--- CDK build and tests complete ---"
echo ""

# ── 3. CDK synth ──────────────────────────────────────────────────────────────
echo "--- Running CDK synth for environment: $ENV ---"
npx cdk synth --context env="$ENV" --all --quiet

echo ""
echo "=== Build complete ==="
echo "CloudFormation templates are in: Medyrax-cdk/cdk.out/"
