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

# Compile Blueprint UI files
echo ""
echo "Compiling Blueprint UI files..."
if command -v blueprint-compiler > /dev/null 2>&1; then
    cd src/gtkpass/ui/blueprints
    blueprint-compiler batch-compile . . *.blp
    cd /workspaces/gtkpass
    echo "✓ Blueprint files compiled"
else
    echo "⚠ Warning: blueprint-compiler not available"
fi

# Compile GSettings schemas
echo ""
echo "Compiling GSettings schemas..."
if command -v glib-compile-schemas > /dev/null 2>&1; then
    glib-compile-schemas data/
    echo "✓ GSettings schemas compiled"
else
    echo "⚠ Warning: glib-compile-schemas not available"
fi

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
echo "To run the app:"
echo "  ./run_app.sh"
echo "  OR: uv run gtkpass"
echo ""
echo "To run tests:"
echo "  uv run pytest tests/"
echo ""
echo "Note: GUI apps require X11 forwarding from your host."
echo "Make sure DISPLAY is set and xhost allows connections."
echo ""
echo "GSettings persistence:"
echo "  Using keyfile backend - settings persist in file storage."
echo "  No D-Bus/dconf required!"
echo "  Schema: $PWD/data/org.ronny_pfannschmidt.gtkpass.gschema.xml"
