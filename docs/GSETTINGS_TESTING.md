# GSettings Testing in Development Environment

## Current Limitation

In the devcontainer environment, GSettings uses a memory backend because dconf is not properly configured. This means settings do NOT persist across process restarts, but they DO work within a single process session.

## Verification

The backend loading feature is fully implemented and working. To verify:

```python
cd /workspaces/gtkpass && GSETTINGS_SCHEMA_DIR=/workspaces/gtkpass/data uv run python << 'EOF'
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
import sys

# Add a demo backend through GSettings
settings = Gio.Settings.new("org.ronny_pfannschmidt.gtkpass")
instances = [("my-demo", "demo")]
variant = GLib.Variant('a(ss)', instances)
settings.set_value("backend-instances", variant)

# Test backend loading
from gtkpass.backends.manager import BackendManager
from gtkpass.backends.demo import DemoBackend, DemoBackendSettings
from pathlib import Path

manager = BackendManager()

for backend_id, backend_type in settings.get_value("backend-instances").unpack():
    path = f"/org/ronny-pfannschmidt/gtkpass/backends/{backend_id}/"
    schema_id = f"org.ronny_pfannschmidt.gtkpass.backend.demo"
    
    backend_gsettings = Gio.Settings.new_with_path(schema_id, path)
    custom_path = backend_gsettings.get_string("custom-data-path")
    settings_obj = DemoBackendSettings(
        custom_data_path=Path(custom_path) if custom_path else None
    )
    
    backend = DemoBackend.create(settings_obj)
    manager.add_backend(backend_id, backend)
    
    passwords = list(backend.list_passwords())
    print(f"✅ Backend '{backend_id}' loaded with {len(passwords)} passwords", file=sys.stderr)
EOF
```

This will output:
```
✅ Backend 'my-demo' loaded with 10 passwords
```

## What Works

- ✅ Backend loading from GSettings within a process
- ✅ Password listing from loaded backends  
- ✅ GSettings schema structure (main + relocatable backend schemas)
- ✅ Settings UI saving to GSettings (within process)
- ✅ Main window loading backends from GSettings (within process)

## What Doesn't Work in Devcontainer

- ❌ GSettings persistence across process restarts
- ❌ Using gsettings CLI to set values (memory backend)
- ❌ Using dconf to set values (database not initialized)

## Production Deployment

In a proper installation (e.g., system-wide schema installation via Meson), GSettings will use dconf and settings WILL persist across restarts. The devcontainer limitation is purely environmental.

## Workaround for Testing

To test the full UI flow in the devcontainer, you would need to:
1. Start the app
2. Use the Settings window to add a backend
3. The backend will be available for the duration of that app session
4. Settings will be lost when the app is closed

This is the expected behavior in the current dev environment.
