#!/bin/bash
set -e

echo "========================================="
echo "Setting up GTKPass development environment"
echo "========================================="

# Ensure we're in the project root
cd /workspaces/gtkpass

# Install dependencies with uv
echo "Installing gtkpass with uv..."
uv sync --all-extras

# Compile Blueprint UI files and the GSettings schema.
# blueprint-compiler is a locked dev dependency, so this cannot silently skip.
echo ""
echo "Compiling Blueprint UI files and GSettings schemas..."
make ui schemas

# Setup GSettings with keyfile backend (file-based, persistent, no D-Bus)
echo ""
echo "Configuring GSettings with keyfile backend..."
echo "export GSETTINGS_BACKEND=keyfile" >> ~/.bashrc
echo "export GSETTINGS_BACKEND=keyfile" >> ~/.zshrc
echo "✓ Keyfile backend configured (persistent, no D-Bus required)"
echo "  Settings will persist in ~/.local/share/glib-2.0/settings/"

# Configure D-Bus session bus for Secret Service support
echo ""
echo "Configuring D-Bus for Secret Service..."
echo "export DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/host-runtime/bus" >> ~/.bashrc
echo "export DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/host-runtime/bus" >> ~/.zshrc
echo "✓ D-Bus session bus configured"
echo "  Secret Service will use host's GNOME Keyring"

# Verify installation
echo ""
echo "Verifying installation..."
if uv run python -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk; print('✓ GTK4 is available')"; then
    echo "✓ gtkpass installed successfully"
else
    echo "⚠ Warning: GTK4 import check failed"
fi

echo ""
echo "========================================="
echo "Setup complete!"
echo "========================================="
echo ""
echo "Common commands (see 'make help'):"
echo "  make run     launch the app"
echo "  make test    run the suite headless"
echo "  make check   lint, format and type checks"
echo "  make ui      recompile .blp -> .ui after editing a blueprint"
echo ""
echo "Note: GUI apps require X11 forwarding from your host."
echo "Make sure DISPLAY is set and xhost allows connections."
echo ""
echo "GSettings persistence:"
echo "  Using keyfile backend - settings persist in file storage."
echo "  No D-Bus/dconf required!"
echo "  Schema: $PWD/data/io.github.RonnyPfannschmidt.GTKPass.gschema.xml"
