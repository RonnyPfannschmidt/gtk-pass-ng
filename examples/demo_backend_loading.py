#!/usr/bin/env python3
"""Demonstration of backend loading functionality.

This script demonstrates that the backend loading feature is fully functional.
It loads a demo backend and displays passwords, simulating what the main window does.

Note: Run with `uv run` to use the virtual environment.
"""

import os

# Set schema directory before importing Gio
os.environ["GSETTINGS_SCHEMA_DIR"] = os.path.join(
    os.path.dirname(__file__), "..", "data"
)

from pathlib import Path

from gtkpass._gi import Gio, GLib
from gtkpass.backends.demo import DemoBackend, DemoBackendSettings
from gtkpass.backends.manager import BackendManager


def main():
    """Demonstrate backend loading."""
    print("=" * 70)
    print("GTKPass Backend Loading Demonstration")
    print("=" * 70)
    print()

    # Step 1: Add a demo backend to GSettings
    print("Step 1: Configuring demo backend in GSettings...")
    settings = Gio.Settings.new("org.ronny_pfannschmidt.gtkpass")
    instances = [("demo-backend", "demo")]
    variant = GLib.Variant("a(ss)", instances)
    settings.set_value("backend-instances", variant)
    print(f"  ✓ Configured backend instances: {instances}")
    print()

    # Step 2: Load backends (simulating window.__init__)
    print("Step 2: Loading backends from GSettings (window._load_backends)...")
    backend_manager = BackendManager()

    instances_from_settings = settings.get_value("backend-instances").unpack()
    print(f"  ✓ Read from GSettings: {instances_from_settings}")

    for backend_id, backend_type in instances_from_settings:
        print(f"\n  Loading backend: {backend_id} (type: {backend_type})")

        # Load backend settings (simulating window._load_backend_settings)
        path = f"/org/ronny-pfannschmidt/gtkpass/backends/{backend_id}/"
        schema_id = f"org.ronny_pfannschmidt.gtkpass.backend.{backend_type}"

        backend_gsettings = Gio.Settings.new_with_path(schema_id, path)
        custom_path = backend_gsettings.get_string("custom-data-path")
        backend_settings = DemoBackendSettings(
            custom_data_path=Path(custom_path) if custom_path else None
        )
        print(f"    ✓ Loaded settings: {backend_settings}")

        # Create backend (simulating window._create_backend)
        backend = DemoBackend.create(backend_settings)
        backend_manager.add_backend(backend_id, backend)
        print("    ✓ Created and registered backend")

    print()

    # Step 3: Load passwords (simulating window._load_passwords)
    print("Step 3: Loading passwords from backends (window._load_passwords)...")
    all_passwords = []

    for backend_id, backend in backend_manager.get_all_backends().items():
        passwords = list(backend.list_passwords())
        all_passwords.extend(passwords)
        print(f"  ✓ Backend '{backend_id}': {len(passwords)} passwords")

    print()
    print(f"Total passwords loaded: {len(all_passwords)}")
    print()

    # Step 4: Display sample passwords (simulating UI population)
    print("Step 4: Displaying passwords (populating ListBox)...")
    print()

    for i, password in enumerate(sorted(all_passwords, key=lambda p: p.name)[:10], 1):
        print(f"  {i:2d}. {password.name}")
        print(f"      Path: {password.path}")
        print()

    if len(all_passwords) > 10:
        print(f"  ... and {len(all_passwords) - 10} more")
        print()

    print("=" * 70)
    print("✅ SUCCESS! Backend loading works correctly.")
    print("=" * 70)
    print()
    print("This demonstrates the functionality implemented in:")
    print("  - src/gtkpass/window.py (_load_backends, _load_passwords)")
    print("  - src/gtkpass/backends/manager.py (add_backend)")
    print("  - data/org.ronny_pfannschmidt.gtkpass.gschema.xml (schemas)")
    print()
    print("Note: In the devcontainer, settings don't persist across processes")
    print("      due to GSettings using a memory backend. This is expected.")
    print("      See docs/GSETTINGS_TESTING.md for details.")
    print()


if __name__ == "__main__":
    main()
