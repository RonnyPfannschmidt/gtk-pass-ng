#!/bin/bash
# Convenience script to run gtkpass with uv

cd "$(dirname "$0")" || exit 1

# Set GSettings schema directory for development
export GSETTINGS_SCHEMA_DIR="$PWD/data"

# Run the application with uv
exec uv run gtkpass "$@"
