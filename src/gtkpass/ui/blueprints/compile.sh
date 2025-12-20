#!/bin/bash
# Compile all Blueprint files in the current directory

set -e

# Always run from project root
cd "$(dirname "$0")/../../../.."

if ! command -v blueprint-compiler > /dev/null 2>&1; then
    echo "Error: blueprint-compiler not found"
    echo "Install it in the devcontainer or run: pip install git+https://gitlab.gnome.org/jwestman/blueprint-compiler.git"
    exit 1
fi

echo "Compiling Blueprint files..."
cd src/gtkpass/ui/blueprints
blueprint-compiler batch-compile . . *.blp

echo "✓ Blueprint compilation complete"
