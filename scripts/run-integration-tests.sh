#!/usr/bin/env bash
# =============================================================================
# run-integration-tests.sh — Runs LocalStack-based integration tests
#
# Prerequisites:
#   - Docker must be running (for TestContainers / LocalStack)
#   - Java 21 must be on PATH
#   - Maven must be on PATH
#
# Usage:
#   ./scripts/run-integration-tests.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Medyrax™ Integration Tests (LocalStack) ==="

# Ensure Docker is running
if ! docker info &>/dev/null; then
    echo "ERROR: Docker is not running. Please start Docker and try again."
    exit 1
fi

cd "$REPO_ROOT"

# Build without tests first to ensure all JARs are up-to-date
echo "--- Building Lambda modules (skip unit tests) ---"
mvn clean package -DskipTests=true -T 4 -q

# Run integration tests using Maven Failsafe plugin
echo "--- Running integration tests ---"
cd "$REPO_ROOT/integration-tests"
mvn verify -Pfailsafe

echo ""
echo "=== Integration tests complete ==="
