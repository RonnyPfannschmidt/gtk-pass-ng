#!/bin/bash
# Convenience script to run gtkpass with uv

cd "$(dirname "$0")" || exit 1

# Set GSettings to use keyfile backend (file-based, no D-Bus needed)
# This provides persistence without requiring dconf-service
export GSETTINGS_BACKEND=keyfile
export GSETTINGS_SCHEMA_DIR="$PWD/data"

# Run the application with uv
exec uv run gtkpass "$@"
