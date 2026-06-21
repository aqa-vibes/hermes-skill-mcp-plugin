#!/usr/bin/env bash
# ============================================
# Hermes skill-mcp CI Test Runner
# ============================================
# Runs full test suite in Docker container.
# Usage:
#   ./scripts/run-tests.sh              # unit + integration (skips E2E without API key)
#   HERMES_API_KEY=sk-... ./scripts/run-tests.sh  # full suite including E2E
# ============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Building test image ==="
docker build -f Dockerfile.test -t hermes-skill-mcp-test:ci .

echo ""
echo "=== Running tests ==="
docker run --rm \
    --name hermes-skill-mcp-test-ci \
    -e HERMES_API_KEY="${HERMES_API_KEY:-}" \
    -e HERMES_API_URL="${HERMES_API_URL:-https://openrouter.ai/api/v1}" \
    -e HERMES_API_MODEL="${HERMES_API_MODEL:-deepseek-v4-flash}" \
    hermes-skill-mcp-test:ci \
    pytest tests/ -v --tb=short --color=yes \
    "$@"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "=== All tests passed ==="
else
    echo ""
    echo "=== Tests failed with exit code $EXIT_CODE ==="
fi

exit $EXIT_CODE
