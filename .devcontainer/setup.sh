#!/bin/bash
set -e

echo "========================================="
echo "Setting up GTKPass development environment"
echo "========================================="

# Create and configure virtual environment
echo "Creating Python virtual environment..."
python3 -m venv .venv

# Install the package in editable mode with dev dependencies
echo "Installing gtkpass in editable mode..."
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e ".[dev]"

# Verify installation
echo ""
echo "Verifying installation..."
if .venv/bin/python -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk; print('✓ GTK4 is available')"; then
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
echo "  source .venv/bin/activate"
echo "  python -m gtkpass"
echo ""
echo "To run tests:"
echo "  source .venv/bin/activate"
echo "  pytest tests/"
echo ""
echo "Note: GUI apps require X11 forwarding from your host."
echo "Make sure DISPLAY is set and xhost allows connections."
