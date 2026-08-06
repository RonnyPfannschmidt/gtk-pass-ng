#!/bin/bash
# Convenience script to run gtkpass with uv

cd "$(dirname "$0")" || exit 1

# Set GSettings to use keyfile backend (file-based, no D-Bus needed)
# This provides persistence without requiring dconf-service
export GSETTINGS_BACKEND=keyfile
export GSETTINGS_SCHEMA_DIR="$PWD/data"

# GLib reads gschemas.compiled and ignores the .xml entirely, so a stale
# compiled blob silently wins whenever the schema changes. Rebuild it.
glib-compile-schemas data/ || exit 1

# Configure D-Bus for Secret Service support (uses host's keyring)
# In devcontainer, the host runtime is mounted to /tmp/host-runtime
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/tmp/host-runtime/bus}"

# This is the application actually being used, so it may open the real store.
# Nothing else should: see src/gtkpass/safety.py.
export GTKPASS_ALLOW_REAL_STORE=1

# Unbuffer Python output for better logging visibility
export PYTHONUNBUFFERED=1

# Run the application with uv
# Use --debug or -d for debug logging
# Use --log-level=LEVEL or -l LEVEL for custom level
# Example: ./run_app.sh --debug
# Example: ./run_app.sh --log-level=WARNING
exec uv run gtkpass "$@"
