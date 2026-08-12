#!/usr/bin/env bash
# Run a command in a throwaway desktop session: its own X server, its own D-Bus
# session, and -- the part nobody expects -- its own XDG_RUNTIME_DIR.
#
#   scripts/headless-session.sh uv run pytest
#
# Every headless invocation in this project goes through here: `make test` and
# `make test-gui`, packaging/test-sysext.sh, and the test jobs in CI. It is one
# definition on purpose. Each of the three things below was learned the hard way
# and reintroducing any of them is easy if the wrapper is bypassed "just here".
#
# Its own X server, and GDK actually pointed at it. GDK ignores DISPLAY whenever
# WAYLAND_DISPLAY is set, and a Wayland session commonly exports
# GDK_BACKEND=wayland outright, so xvfb-run on its own connected to the
# developer's own compositor: windows appeared on their screen and the clipboard
# tests overwrote whatever they had copied -- which, working on this, may well
# have been a password. Xvfb was started, and nothing used it.
#
# Its own bus, which keeps the tests away from the real keyring: a private
# session bus has no secret service on it.
#
# Its own runtime directory, which keeps them away from the real *document
# portal*. xdg-document-portal derives its mountpoint from
# g_get_user_runtime_dir(), i.e. $XDG_RUNTIME_DIR/doc, and dbus-run-session
# inherits XDG_RUNTIME_DIR from the surrounding session. So the moment anything
# on the test bus activated org.freedesktop.portal.Documents, dbus-daemon
# started a *second* portal aimed at the same /run/user/$UID/doc as the real
# one. That mount is created with auto_unmount: when the test bus exited its
# portal child died and the mount went with it -- taking the real session's
# mount away, after which every flatpak on the machine failed to launch with
#
#     bwrap: Can't find source path /run/user/1000/doc/by-app/<app-id>
#
# while the real xdg-document-portal.service still reported active (running)
# with no restarts and nothing in its journal, because it was never the process
# that died. `systemctl status` will tell you everything is fine; `findmnt
# /run/user/$UID/doc` is the check that answers the question.
#
# Two things about the fix. It is a *private* directory, not an unset variable:
# with XDG_RUNTIME_DIR unset, g_get_user_runtime_dir() falls back to the user
# cache directory and the portal mounts at ~/.cache/doc instead
# (xdg-desktop-portal#512). And it has to be set out here, around
# dbus-run-session. Setting it in conftest.py is too late and does nothing:
# dbus-daemon is already running by then, and it starts activated services with
# its own environment rather than pytest's.
set -euo pipefail

if [ "$#" -eq 0 ]; then
    echo "usage: $0 COMMAND [ARGS...]" >&2
    exit 2
fi

# Under the real runtime directory when there is one. It is a tmpfs, it is
# already 0700, and -- the reason it is worth the conditional -- it is short:
# AF_UNIX paths are capped near 108 bytes, so a bus socket under a long prefix
# fails in a way that looks like anything at all except a path length. /tmp is
# the fallback for a CI container, which has no runtime directory.
base="${XDG_RUNTIME_DIR:-/tmp}"
[ -d "$base" ] || base=/tmp
runtime=$(mktemp -d "$base/gtkpass-session.XXXXXX")
# D-Bus refuses a runtime directory anyone else could reach into.
chmod 700 "$runtime"

# Everything mounted at or under the private directory, deepest first so a
# nested mount comes off before whatever contains it. Read out of the mount
# table rather than tested with `mountpoint`, because the set is not known in
# advance: the portal's doc/ is the one this exists for, but a suite run also
# brings up gvfsd-fuse, and the next service to want a mountpoint will not
# announce itself either.
mounts_under() {
    awk -v dir="$runtime" \
        '$2 == dir || index($2, dir "/") == 1 { print $2 }' \
        /proc/self/mounts | sort -r
}

# These are all auto_unmount and go away with the bus, so this should normally
# find nothing and be left removing an empty doc/, a gvfs/ and a dbus-1/.
# Should: deleting through a live FUSE mount is how the real portal got emptied
# in the first place, so check rather than assume, and leave the directory on
# disk rather than recurse into something still mounted.
cleanup() {
    local status=$? mount remaining
    trap - EXIT INT TERM HUP
    while IFS= read -r mount; do
        [ -n "$mount" ] || continue
        fusermount3 -u "$mount" 2>/dev/null ||
            fusermount -u "$mount" 2>/dev/null || true
    done <<<"$(mounts_under)"
    remaining=$(mounts_under)
    if [ -n "$remaining" ]; then
        echo "$0: leaving $runtime in place, still mounted:" >&2
        while IFS= read -r mount; do
            echo "    $mount" >&2
        done <<<"$remaining"
    else
        rm -rf "$runtime"
    fi
    exit "$status"
}
# EXIT alone is not enough: a Ctrl-C part way through a suite kills the shell
# without running it, and the runtime directory outlives the run.
trap cleanup EXIT INT TERM HUP

# And a screen size that is said rather than inherited. GTK will not give a
# window more room than the monitor has, so the desktop this invents is an upper
# bound on every width a test can ask for -- and xvfb-run carries a default that
# differs by where it came from: Fedora's is 640x480, Homebrew's is this. A
# window presented at 1000 points on the smaller one is silently 640 instead,
# which is under the breakpoint, so the test for a wide window read the layout of
# a narrow one and asserted the opposite of what it meant. It passed on the
# machine it was written on and failed in CI, and neither said anything about a
# screen.
#
# Larger than any window the suite presents, and 24-bit because the cairo
# renderer wants a truecolor visual.
SCREEN="-screen 0 1280x1024x24"

status=0
env -u WAYLAND_DISPLAY GDK_BACKEND=x11 XDG_RUNTIME_DIR="$runtime" \
    xvfb-run -a -s "$SCREEN" dbus-run-session -- "$@" || status=$?
exit "$status"
