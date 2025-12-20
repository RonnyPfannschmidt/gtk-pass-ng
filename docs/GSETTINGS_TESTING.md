# GSettings Testing in Development Environment

## Current Configuration

The devcontainer now uses GSettings **keyfile backend** for persistent storage. This is a file-based backend that doesn't require D-Bus or dconf, making it perfect for containerized development.

## How It Works

- **Backend**: `keyfile` (file-based, not memory or dconf)
- **Storage**: Settings are stored in files (typically ~/.local/share/glib-2.0/settings/)
- **Persistence**: ✅ Settings persist across process restarts
- **Dependencies**: None (no D-Bus, no dconf-service required)

The keyfile backend is automatically configured in:
- `run_app.sh`: Sets `GSETTINGS_BACKEND=keyfile`
- `.devcontainer/setup.sh`: Adds to shell rc files

## Verification

To verify persistence works:

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
- ✅ Settings UI saving to GSettings
- ✅ Main window loading backends from GSettings
- ✅ **Settings persistence across process restarts** (keyfile backend)
- ✅ No D-Bus or dconf required

## Backend Comparison

| Backend | Persistence | D-Bus Required | Use Case |
|---------|-------------|----------------|----------|
| keyfile | ✅ Yes | ❌ No | Development, containers, testing |
| dconf | ✅ Yes | ✅ Yes | Production desktop environments |
| memory | ❌ No | ❌ No | Temporary/testing only |

## Production Deployment

In system-wide installations, GSettings will automatically use dconf when available. The keyfile backend is specifically configured for development convenience.
