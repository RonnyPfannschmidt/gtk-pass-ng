#!/usr/bin/env bash
# Merge the sysext image onto *this* machine, check the application works, and
# take it away again.
#
#   packaging/test-sysext.sh            merge, test, unmerge
#   packaging/test-sysext.sh --keep     merge, test, leave it merged
#
# This is the step CI cannot do: systemd-sysext needs a running systemd and a
# writable /run, so a container can only inspect the image. Here it gets merged
# for real.
#
# What it changes, and for how long: it copies the image into
# /var/lib/extensions/ and runs `systemd-sysext merge`, which overlays the
# image's /usr onto the running system. Nothing is written to /usr itself --
# the merge is an overlay, and unmerging takes it off. Without --keep the image
# is removed from /var/lib/extensions/ at the end, so the state is restored
# even across a reboot.
#
# It needs root for the merge, and will ask sudo for it.
set -euo pipefail

cd "$(dirname "$0")/.."

NAME=gtkpass
KEEP=0
if [ "${1:-}" = "--keep" ]; then
    KEEP=1
fi

target_id=$(. /etc/os-release && echo "$ID")
target_version=$(. /etc/os-release && echo "$VERSION_ID")
image="dist/sysext/${NAME}-${target_id}-${target_version}.raw"

if [ ! -f "$image" ]; then
    echo "==> no image for ${target_id} ${target_version}, building one"
    packaging/build-sysext.sh
fi

echo "==> inspecting before merging anything"
packaging/inspect-sysext.sh "$image"

# systemd-sysext merges everything in /var/lib/extensions at once, and unmerges
# the same way. Someone with other extensions in place would have them taken
# down and put back by this script, which is theirs to decide rather than mine
# to assume.
others=$(find /var/lib/extensions -mindepth 1 -maxdepth 1 \
    ! -name "${NAME}-*" -printf '%f\n' 2>/dev/null || true)
if [ -n "$others" ]; then
    echo
    echo "note: other extensions are installed, and merge/unmerge covers them all:"
    echo "$others" | sed 's/^/      /'
    echo
    read -r -p "continue? [y/N] " reply
    [ "$reply" = "y" ] || { echo "stopped."; exit 1; }
fi

merged_before=0
if systemd-sysext status 2>/dev/null | grep -q "$NAME"; then
    merged_before=1
fi

cleanup() {
    local status=$?
    echo
    if [ "$KEEP" = "1" ]; then
        echo "==> left merged, as asked. To undo:"
        echo "    sudo systemd-sysext unmerge"
        echo "    sudo rm /var/lib/extensions/$(basename "$image")"
    else
        echo "==> unmerging"
        sudo systemd-sysext unmerge || true
        sudo rm -f "/var/lib/extensions/$(basename "$image")"
        # Anything that was merged before this ran was merged by someone else,
        # and unmerge took it down along with ours.
        if [ "$merged_before" = "1" ]; then
            sudo systemd-sysext merge || true
        fi
    fi
    exit $status
}
trap cleanup EXIT

echo "==> merging"
sudo mkdir -p /var/lib/extensions
sudo cp "$image" /var/lib/extensions/
sudo systemd-sysext merge
systemd-sysext status

echo
echo "==> the merge put the application on the system"
# Reading through the overlay rather than the image: this is the question the
# inspection could not answer.
test -x /usr/bin/gtkpass || { echo "FAIL: /usr/bin/gtkpass is not there"; exit 1; }

echo "==> and did not relabel the host's /usr/lib"
# The check the inspection can only make against the image. A merged directory
# takes its attributes from the layer above, so an extension carrying the wrong
# label for usr/lib puts that label on the whole system's /usr/lib -- which on a
# Fedora ostree is where the system users live, and confined services that
# cannot search it lose the ability to look up their own. dnsmasq is the one
# that says so out loud; issue #23 has the rest. Reading it here, through the
# merge, is the only place the answer is the real one.
merged_context=$(getfattr -n security.selinux --absolute-names /usr/lib 2>/dev/null \
    | sed -n 's/^security\.selinux="\(.*\)"$/\1/p')
# On the type rather than the whole context: an MLS host ranges the level, and
# the type is what a confined domain is refused on.
case "$merged_context" in
    "") echo "    (no SELinux on this machine, so nothing to check)" ;;
    *:lib_t:*) echo "    /usr/lib is ${merged_context}" ;;
    *)
        echo "FAIL: merging relabelled /usr/lib to ${merged_context}."
        echo "      Confined services will not be able to look up their users."
        exit 1
        ;;
esac

echo "==> smoke testing what is now installed"
# In a throwaway session even though this machine has a real one: a private bus
# has no secret service, so nothing here can reach the real keyring; a window
# opening on the developer's own display is not the thing being tested; and a
# private runtime directory is what stops the throwaway session's document
# portal from unmounting the real session's. See scripts/headless-session.sh --
# this runs on a live desktop, so it is the call site with the most to lose.
scripts/headless-session.sh packaging/smoke-test-install.sh

echo
echo "==> the merged extension works"
