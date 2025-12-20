#!/bin/bash
# Run tests for GTKPass

set -e

cd "$(dirname "$0")" || exit 1

echo "Running GTKPass test suite..."
echo ""

# Run linting
echo "1. Running linter (ruff)..."
uv run ruff check src/ tests/
echo "✓ Linting passed"
echo ""

# Run formatting check
echo "2. Checking code formatting..."
uv run ruff format --check src/ tests/
echo "✓ Formatting check passed"
echo ""

# Run tests
echo "3. Running tests..."
uv run pytest tests/ -v
echo "✓ Tests passed"
echo ""

echo "All checks passed! ✓"
