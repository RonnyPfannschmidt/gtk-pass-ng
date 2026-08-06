#!/bin/bash
# Check display backend availability in the devcontainer

echo "========================================"
echo "Display Backend Check"
echo "========================================"
echo ""

echo "Environment Variables:"
echo "  WAYLAND_DISPLAY: ${WAYLAND_DISPLAY:-<not set>}"
echo "  DISPLAY:         ${DISPLAY:-<not set>}"
echo "  GDK_BACKEND:     ${GDK_BACKEND:-<not set>}"
echo "  XDG_RUNTIME_DIR: ${XDG_RUNTIME_DIR:-<not set>}"
echo ""

echo "Wayland Socket:"
if [ -n "$WAYLAND_DISPLAY" ]; then
    WAYLAND_PATH="$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
    if [ -e "$WAYLAND_PATH" ]; then
        echo "  ✓ Wayland socket exists at $WAYLAND_PATH"
        if [ -L "$WAYLAND_PATH" ]; then
            REAL_PATH=$(readlink -f "$WAYLAND_PATH")
            echo "    (symlink to $REAL_PATH)"
        fi
    else
        echo "  ✗ Wayland socket NOT found at $WAYLAND_PATH"
    fi
else
    echo "  - WAYLAND_DISPLAY not set"
fi
echo ""

echo "X11 Socket:"
if [ -n "$DISPLAY" ]; then
    if [ -S "/tmp/.X11-unix/X${DISPLAY##*:}" ] || [ -d "/tmp/.X11-unix" ]; then
        echo "  ✓ X11 socket directory exists at /tmp/.X11-unix"
    else
        echo "  ✗ X11 socket directory NOT found"
    fi
else
    echo "  - DISPLAY not set"
fi
echo ""

echo "D-Bus Socket:"
DBUS_SOCKET="$XDG_RUNTIME_DIR/bus"
if [ -S "$DBUS_SOCKET" ]; then
    echo "  ✓ D-Bus socket exists at $DBUS_SOCKET"
elif [ -n "$DBUS_SESSION_BUS_ADDRESS" ]; then
    echo "  ✓ D-Bus configured via DBUS_SESSION_BUS_ADDRESS"
    echo "    ($DBUS_SESSION_BUS_ADDRESS)"
else
    echo "  ⚠ D-Bus socket NOT found at $DBUS_SOCKET"
    echo "    (App may still work without D-Bus)"
fi
echo ""

echo "GTK Backend Preference:"
if [ -n "$GDK_BACKEND" ]; then
    echo "  GDK will try: $GDK_BACKEND (in order)"
else
    echo "  GDK will auto-detect (Wayland preferred)"
fi
echo ""

echo "========================================"
echo "Recommendation:"
WAYLAND_PATH="$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY"
if [ -e "$WAYLAND_PATH" ]; then
    echo "  ✓ Use Wayland (recommended)"
elif [ -d "/tmp/.X11-unix" ]; then
    echo "  ✓ Use X11"
else
    echo "  ⚠ No display backend detected!"
    echo "    Rebuild the devcontainer to apply changes."
fi
echo "========================================"
