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

# This is the application actually being used, so it may open the real store
# and the keyring. Nothing else should: see src/gtkpass/safety.py.
#
# Defaulted rather than assigned, so a caller can turn it back off. `make
# run-dev` passes 0: it launches through this script, and without the default
# form it would inherit the opt-in and run with the guard disabled.
export GTKPASS_ALLOW_REAL_STORE="${GTKPASS_ALLOW_REAL_STORE:-1}"

# Unbuffer Python output for better logging visibility
export PYTHONUNBUFFERED=1

# Reuse the environment as-is. Without this uv re-resolves it and tries to build
# PyGObject and pycairo from source, which fails: they are taken from the
# distribution. The Makefile exports the same thing, so this only matters when
# the script is run directly -- which the documentation tells people to do.
export UV_NO_SYNC=1

# Run the application with uv
# Use --debug or -d for debug logging
# Use --log-level=LEVEL or -l LEVEL for custom level
# Example: ./run_app.sh --debug
# Example: ./run_app.sh --log-level=WARNING
exec uv run gtkpass "$@"
