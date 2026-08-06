# Backend Integration Test Results

## Issue Summary

**Problem:** User adds a demo backend in Preferences but no data shows in the GUI.

**Root Cause:** The main window (`GTKPassWindow`) does not load backends from GSettings or display password data.

## Test Results

### ✅ Working Components

1. **Demo Backend** (`test_demo_backend_has_passwords`)
   - Demo backend successfully creates with 10 sample passwords
   - All passwords have names and paths

2. **Backend Data Retrieval** (`test_demo_backend_get_password_works`)
   - `get_password(name)` works correctly when given the password name
   - Returns full password details including username, password, URL

3. **Settings Persistence** (GSettings schema)
   - Backend configurations can be saved to GSettings
   - Multiple backend types supported (demo, secretservice, pass, direct)
   - Each backend instance has dedicated path: `/org/ronny-pfannschmidt/gtkpass/backends/{id}/`

### ❌ Missing Implementation

1. **Main Window Backend Loading** (`test_main_window_needs_backend_loading` - SKIPPED)
   - Main window shows only "No Backends Configured" message
   - Does not read backend-instances from GSettings
   - Does not instantiate backends
   - Does not display password list from backends

## Required Fixes

To make backends work end-to-end:

1. **Update `GTKPassWindow.__init__`:**
   - Read `backend-instances` from GSettings
   - Load backend settings for each instance
   - Create backend instances using `Backend.create(settings)`
   - Populate password list from backends

2. **Update `GTKPassWindow._setup_password_list`:**
   - If backends exist, load passwords from them
   - Only show "No Backends Configured" if backend-instances is empty

3. **Add Backend Manager Integration:**
   - Use `BackendManager` to manage multiple backend instances
   - Handle backend errors gracefully
   - Support adding/removing backends at runtime

## Test Coverage

```
src/gtkpass/backends/demo.py       70%  ✅ Core backend logic working
src/gtkpass/window.py               0%  ❌ No backend integration
src/gtkpass/ui/settings.py          0%  ⚠️  Settings UI not tested (GTK segfaults in CI)
```

## Next Steps

1. Implement backend loading in `GTKPassWindow`
2. Update `_setup_password_list` to display backend data
3. Add test: `test_window_loads_backends_on_startup`
4. Add test: `test_window_displays_passwords_from_backend`
