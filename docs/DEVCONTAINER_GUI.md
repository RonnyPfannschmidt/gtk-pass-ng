# Running GTKPass in a Dev Container

This guide explains how to run the GTKPass GUI application from within the dev container.

## Prerequisites on Host Machine

For the GTKPass GUI to display from the dev container, you need either:

1. **Wayland compositor** (preferred on modern Linux) - works out of the box
2. **X11 Server** with X11 forwarding configured
3. **D-Bus session** accessible (required for both)

The devcontainer is configured to support **both Wayland and X11**, automatically preferring Wayland when available.

### Linux Host (Wayland)

On modern Linux with Wayland (GNOME, KDE Plasma 6, Sway, etc.), **it should work out of the box** with no extra configuration needed! The container will use your Wayland session.

To verify you're using Wayland:
```bash
# On host
echo $WAYLAND_DISPLAY  # Should show 'wayland-0' or similar
```

### Linux Host (X11)

### Linux Host (X11)

On Linux using X11, allow container access:

```bash
# Allow local connections to X server
xhost +local:
```

### macOS Host

Install XQuartz:

```bash
brew install --cask xquartz
```

Configure XQuartz:
1. Open XQuartz
2. Go to Preferences → Security
3. Check "Allow connections from network clients"
4. Restart XQuartz

Then allow connections:
```bash
xhost +localhost
```

### Windows Host (WSL2)

If using WSL2, install an X server like VcXsrv or X410, then:

```bash
export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0
xhost +
```

## Running the Application

Once the dev container is set up (which happens automatically on first launch):

```bash
# Simple method - use the convenience script
./run_app.sh

# Or manually activate the virtual environment
source .venv/bin/activate
python -m gtkpass

# Or use the installed command
gtkpass
```

## Troubleshooting

### Check Which Backend is Being Used

```bash
# In the container, run:
echo "WAYLAND_DISPLAY: $WAYLAND_DISPLAY"
echo "DISPLAY: $DISPLAY"
echo "GDK_BACKEND: $GDK_BACKEND"

# Force a specific backend:
GDK_BACKEND=wayland python -m gtkpass  # Force Wayland
GDK_BACKEND=x11 python -m gtkpass      # Force X11
```

### Error: "Unable to acquire session bus"

This means D-Bus isn't accessible. D-Bus is used for desktop integration features but isn't strictly required for the app to run.

Check that:
1. Your host has a D-Bus session running
2. The socket exists at `$XDG_RUNTIME_DIR/bus` on the host

```bash
# On host, check:
echo $XDG_RUNTIME_DIR
ls -la $XDG_RUNTIME_DIR/bus
```

**Note**: In some environments (like VS Code devcontainers), D-Bus may not be available. The app should still run, but some desktop integration features may not work.

### Error: "cannot open display" (X11)

This means X11 forwarding isn't working. Check that:
1. DISPLAY is set in the container: `echo $DISPLAY`
2. X11 socket is mounted: `ls -la /tmp/.X11-unix`
3. You've run `xhost +local:` on the host

```bash
# Test X11 from container:
xclock  # Should show a clock window
```

### Error: Wayland connection issues

If Wayland isn't working:

```bash
# On host, check Wayland socket exists:
ls -la $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY

# In container, check socket is mounted:
ls -la /run/user/1000/$WAYLAND_DISPLAY

# Try forcing X11 instead:
GDK_BACKEND=x11 ./run_app.sh
```

### Permissions Issues

If you get permission errors with X11 or D-Bus:

```bash
# On host:
xhost +local:docker
xhost +local:

# Rebuild the dev container
# In VS Code: Cmd/Ctrl+Shift+P → "Dev Containers: Rebuild Container"
```

## Development Without GUI

If you can't get GUI access working, you can still develop:

```bash
# The suite, headless under xvfb -- no GUI access needed
make test

# Everything that does not touch a widget
UV_NO_SYNC=1 uv run pytest -m "not gui"

# Lint, format and types
make check
```

## Alternative: Run Locally

For the best GUI experience, you can:

1. Install GTK4 on your host machine (see [DEVELOPMENT.md](../DEVELOPMENT.md))
2. Clone the repo locally (not in container)
3. Run directly on your host

This avoids all the X11 forwarding complexity.
