#!/usr/bin/env bash
# Install the sysext image on *this* machine and merge it, replacing any
# earlier one.
#
#   packaging/install-sysext.sh          install and merge
#   packaging/install-sysext.sh --yes    do not stop to confirm
#
# What it changes: it copies the image into /var/lib/extensions/, removes any
# older gtkpass image left there, runs `systemd-sysext merge`, and makes sure
# systemd-sysext.service is enabled so the merge comes back after a reboot.
#
# Nothing is written to /usr. The merge is an overlay, and unmerging takes it
# off; the file in /var/lib/extensions is the whole of what is installed. To
# undo everything this does:
#
#   sudo systemd-sysext unmerge
#   sudo rm /var/lib/extensions/gtkpass-*.raw
#
# packaging/test-sysext.sh is the one that merges, tests and takes it away
# again. This one is for keeping.
#
# It needs root for the merge, and will ask sudo for it.
set -euo pipefail

cd "$(dirname "$0")/.."

NAME=gtkpass
ASSUME_YES=0
if [ "${1:-}" = "--yes" ]; then
    ASSUME_YES=1
fi

confirm() {
    [ "$ASSUME_YES" = "1" ] && return 0
    read -r -p "$1 [y/N] " reply
    [ "$reply" = "y" ] || { echo "stopped."; exit 1; }
}

target_id=$(. /etc/os-release && echo "$ID")
target_version=$(. /etc/os-release && echo "$VERSION_ID")
image="dist/sysext/${NAME}-${target_id}-${target_version}.raw"

if [ ! -f "$image" ]; then
    echo "==> no image for ${target_id} ${target_version}, building one"
    packaging/build-sysext.sh
fi

echo "==> inspecting before changing anything"
packaging/inspect-sysext.sh "$image"

echo
echo "==> this will install onto ${target_id} ${target_version}"
echo "    image:  $image"
echo "    built:  $(date -r "$image" '+%Y-%m-%d %H:%M:%S')"
echo "    commit: $(git log -1 --format='%h %s' 2>/dev/null || echo 'not a checkout')"
echo
# The build date is on screen because this installs whatever was built last,
# rather than building afresh: an image from a week ago looks exactly like one
# from a minute ago once it is merged.
echo "    A sysext survives no upgrade of the deployment underneath it, so a"
echo "    bootc or rpm-ostree update means running this again."

# systemd-sysext merges everything in /var/lib/extensions at once, and unmerges
# the same way, so anyone else's extensions come down and go back up with ours.
others=$(find /var/lib/extensions -mindepth 1 -maxdepth 1 \
    ! -name "${NAME}-*" -printf '%f\n' 2>/dev/null || true)
if [ -n "$others" ]; then
    echo
    echo "note: other extensions are installed, and merge/unmerge covers them all:"
    echo "$others" | sed 's/^/      /'
fi

echo
confirm "install and merge?"

# Unmerge first, always. While an extension is merged its image is loop-mounted,
# so replacing the file underneath it leaves the running overlay reading from a
# file that is no longer there -- and the copy itself can fail outright. This is
# also what makes the target an update rather than a first install: it takes the
# old one down before the new one goes in.
if systemd-sysext status 2>/dev/null | grep -q "$NAME"; then
    echo "==> unmerging the extension that is already there"
    sudo systemd-sysext unmerge
fi

echo "==> installing $(basename "$image")"
sudo mkdir -p /var/lib/extensions

# An image is named for the OS release it was built for, so an upgraded machine
# builds a differently named one and the old file would sit there for ever --
# refused by systemd on the new release, and confusing when reading the
# directory. Ours only; anything else there belongs to somebody else.
for stale in "/var/lib/extensions/${NAME}"-*.raw; do
    [ -e "$stale" ] || continue
    [ "$(basename "$stale")" = "$(basename "$image")" ] && continue
    echo "    removing the earlier $(basename "$stale")"
    sudo rm -f "$stale"
done

sudo cp "$image" /var/lib/extensions/

echo "==> merging"
sudo systemd-sysext merge
systemd-sysext status

# Merging is not persistent by itself: the service is what re-merges at boot.
# It ships enabled on most systems, which is precisely why an unenabled one
# would be missed -- the extension would simply be gone after a reboot, with
# nothing to say why.
if ! systemctl is-enabled --quiet systemd-sysext.service; then
    echo "==> enabling systemd-sysext.service, so this survives a reboot"
    sudo systemctl enable systemd-sysext.service
fi

echo
echo "==> checking the merge put the application on the system"
test -x /usr/bin/gtkpass || { echo "FAIL: /usr/bin/gtkpass is not there"; exit 1; }

echo
echo "==> installed and merged"
echo "    run it with: gtkpass"
echo "    remove it with:"
echo "        sudo systemd-sysext unmerge"
echo "        sudo rm /var/lib/extensions/$(basename "$image")"
