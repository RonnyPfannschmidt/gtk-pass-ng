#!/bin/bash
# Convenience script to run gtkpass with proper environment setup

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "Error: Virtual environment not found. Run setup first:"
    echo "  bash .devcontainer/setup.sh"
    exit 1
fi

# Run the application
exec python -m gtkpass "$@"
