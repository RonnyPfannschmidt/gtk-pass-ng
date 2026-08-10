#!/usr/bin/env bash
# Build a systemd-sysext extension image of GTKPass, for Bluefin, Fedora
# Silverblue and the other ostree desktops.
#
# On those systems /usr is read-only and rpm-ostree install means a rebooted,
# permanently modified image. A sysext is the alternative: a squashfs of /usr
# content that systemd overlays onto the running system, added and removed
# without touching the deployment.
#
#   packaging/build-sysext.sh                    build for the running system
#   SYSEXT_ID=fedora SYSEXT_VERSION_ID=44 \
#       packaging/build-sysext.sh                build for a named upstream
#
# Output lands in dist/sysext/. Install it with:
#
#   sudo cp dist/sysext/gtkpass-<id>-<version>.raw /var/lib/extensions/
#   sudo systemd-sysext merge
#
# and take it away again with `sudo systemd-sysext unmerge`. Extensions are
# re-merged at boot by systemd-sysext.service.
set -euo pipefail

cd "$(dirname "$0")/.."

NAME=gtkpass

# An extension names the operating system it was built for, and systemd refuses
# to merge it anywhere else. That check is the whole safety of this: the image
# carries a wheel installed into /usr/lib/python3.N/site-packages, a path that
# names the interpreter, so merged onto a host whose Python is a different
# version it lands somewhere nothing imports from and the application is
# missing rather than broken -- which is the better half of what can go wrong.
#
# systemd would accept ID=_any and skip the check. This deliberately does not
# offer it: an image that merges anywhere is an image that was tested nowhere.
# One build per target instead, defaulting to the machine doing the building.
SYSEXT_ID="${SYSEXT_ID:-$(. /etc/os-release && echo "$ID")}"
SYSEXT_VERSION_ID="${SYSEXT_VERSION_ID:-$(. /etc/os-release && echo "$VERSION_ID")}"

if [ "$SYSEXT_ID" = "_any" ]; then
    echo "error: ID=_any would merge onto any system, including ones this was" >&2
    echo "       never built against. Name the target instead." >&2
    exit 1
fi

# systemd looks for usr/lib/extension-release.d/extension-release.$IMAGE inside
# the image, where $IMAGE is the image's own file name without the .raw suffix.
# Name them apart and systemd-dissect reports "✗ sysext for system" and the
# merge fails with "No medium found" -- which names neither the file nor the
# mismatch. So there is one name here, and both are built from it.
IMAGE_NAME="${NAME}-${SYSEXT_ID}-${SYSEXT_VERSION_ID}"
STAGE="dist/sysext/${IMAGE_NAME}"
IMAGE_OUT="${STAGE}.raw"

# The RPM has to be built for the same target, for the same reason: it is where
# the interpreter version in those paths is decided. The derivatives report
# Fedora's release in VERSION_ID even though ID is their own name, so this is
# usually right; FEDORA_RELEASE overrides it for one that is not.
export FEDORA_RELEASE="${FEDORA_RELEASE:-${SYSEXT_VERSION_ID%%.*}}"

echo "==> target ${SYSEXT_ID} ${SYSEXT_VERSION_ID} (fedora:${FEDORA_RELEASE} build root)"

if [ -z "$(ls dist/rpm/*.noarch.rpm 2>/dev/null)" ]; then
    echo "==> no RPM yet, building one"
    packaging/build-rpm.sh
fi

gtkpass_rpm=$(ls -1 dist/rpm/gtkpass-*.noarch.rpm | head -1)

# An RPM left over from a build for another release would put its files under
# the wrong site-packages, which is exactly what the target check exists to
# prevent -- so catch it here rather than shipping it.
if ! [[ "$gtkpass_rpm" == *".fc${FEDORA_RELEASE}."* ]]; then
    echo "error: $(basename "$gtkpass_rpm") was not built for fc${FEDORA_RELEASE}." >&2
    echo "       Remove dist/rpm and let this rebuild it." >&2
    exit 1
fi

# What the host cannot already satisfy has to travel inside the image. On a
# stock Bluefin that is python3-gnupg and nothing else: GTK4, libadwaita,
# PyGObject, secretstorage, gnupg2, pass and git are all in the base image, and
# shipping second copies of them would be both large and a way to run a
# different GTK than the desktop does.
#
# Resolved against the running system rather than a package list, because the
# answer depends on what the user has layered.
#
# Which means the resolving system has to be one the image is actually for. A
# build dependency installed here is indistinguishable from something the target
# already ships, and the failure is silent: %pyproject_buildrequires pulls in
# python3-gnupg to build the RPM, and an image resolved afterwards leaves it out
# and reaches the target with its Direct GPG backend reporting unavailable.
#
# On the ostree desktops this cannot happen -- rpmbuild runs in a container and
# the host stays clean. Anywhere rpmbuild is installed, it is worth saying so.
if command -v rpmbuild >/dev/null; then
    echo "warning: rpm-build is installed here, so this machine may carry build" >&2
    echo "         dependencies that a target system would not. Anything they" >&2
    echo "         satisfy will be left out of the image. Resolve on a machine" >&2
    echo "         that resembles the target, or check the manifest afterwards." >&2
fi

declare -a bundled=("$gtkpass_rpm")

provided_by_bundle() {
    local capability=$1 rpm
    for rpm in "${bundled[@]}"; do
        if rpm -qp --provides "$rpm" 2>/dev/null | grep -qF "$capability"; then
            return 0
        fi
    done
    return 1
}

missing_requires() {
    local rpm=$1
    rpm -qpR "$rpm" 2>/dev/null \
        | grep -v '^rpmlib(' \
        | sed 's/ [<>=].*//' \
        | grep -v '^$' \
        | while read -r capability; do
            rpm -q --whatprovides "$capability" >/dev/null 2>&1 && continue
            provided_by_bundle "$capability" && continue
            echo "$capability"
        done
}

# Downloading is done in a container for the same reason the RPM is built in
# one: the ostree desktop this targets has no writable package database and no
# dnf worth invoking. CI already runs inside the base image it is building for,
# where dnf is right there and a nested container would be both slower and a
# different Fedora than the one being resolved against.
download_package() {
    local capability=$1
    if [ "${USE_CONTAINER:-1}" = "0" ]; then
        ( cd dist/sysext && dnf download "$capability" >/dev/null )
    else
        # shellcheck source=packaging/container-runtime.sh
        . "$(dirname "$0")/container-runtime.sh"
        "$CONTAINER_RUNTIME" run --rm -v "$PWD/dist/sysext:/out:z" \
            "registry.fedoraproject.org/fedora:${FEDORA_RELEASE}" \
            bash -euo pipefail -c "
                dnf -y install dnf-plugins-core >/dev/null
                cd /out && dnf download '${capability}' >/dev/null
            "
    fi
}

mkdir -p dist/sysext
# A queue rather than one pass: a package pulled in to satisfy the application
# may itself need something the host has not got.
queue=("$gtkpass_rpm")
while [ ${#queue[@]} -gt 0 ]; do
    current=${queue[0]}
    queue=("${queue[@]:1}")

    while read -r capability; do
        [ -n "$capability" ] || continue
        echo "==> vendoring a package for ${capability}"

        before=$(ls -1 dist/sysext/*.rpm 2>/dev/null || true)
        download_package "$capability"
        # Only what this download added. dnf resolves a capability to one
        # package but may write more than one file, and re-queueing something
        # already bundled would extract it twice.
        while IFS= read -r downloaded; do
            [ -n "$downloaded" ] || continue
            bundled+=("$downloaded")
            queue+=("$downloaded")
        done < <(comm -13 <(echo "$before") <(ls -1 dist/sysext/*.rpm 2>/dev/null))
    done < <(missing_requires "$current")
done

echo "==> staging"
rm -rf "$STAGE" "$IMAGE_OUT"
mkdir -p "$STAGE"
for rpm in "${bundled[@]}"; do
    echo "    $(basename "$rpm")"
    rpm2cpio "$rpm" | (cd "$STAGE" && cpio -idmu --quiet)
done
rm -f dist/sysext/*.rpm

# A sysext may only carry /usr and /opt. Everything this package installs is
# under /usr already; this catches a vendored dependency that is not.
for entry in "$STAGE"/*; do
    case "$(basename "$entry")" in
        usr|opt) ;;
        *) echo "error: $entry is outside /usr and /opt" >&2; exit 1 ;;
    esac
done

echo "==> compiling the schema to a private directory"
# Not into /usr/share/glib-2.0/schemas. That directory's gschemas.compiled is a
# single file holding every application's schemas, and an overlay carrying its
# own would hide all of them -- the desktop would come up with GNOME's own
# settings missing. gtkpass/config.py adds this directory to the schema search
# path when it exists, in addition to the default locations rather than instead
# of them, so the RPM -- which does install into the system directory and ships
# nothing here -- is unaffected.
mkdir -p "$STAGE/usr/share/${NAME}/schemas"
cp "$STAGE"/usr/share/glib-2.0/schemas/*.gschema.xml \
    "$STAGE/usr/share/${NAME}/schemas/"
glib-compile-schemas --strict "$STAGE/usr/share/${NAME}/schemas"
rm -rf "$STAGE/usr/share/glib-2.0"

# The same argument applies to every other merged cache: shipping one replaces
# the host's rather than adding to it.
find "$STAGE" \( -name 'icon-theme.cache' -o -name 'mimeinfo.cache' \
    -o -name '*.cache' -a -path '*/share/*' \) -delete
rm -rf "$STAGE/usr/lib/.build-id"

echo "==> manifest"
# What is in here, written into the image itself. The vendoring set is decided
# by asking the running system what it lacks, so it is a property of the machine
# that built this as much as of the project -- and an image that quietly started
# carrying GTK would otherwise look exactly like one that did not.
{
    echo "# Packages unpacked into this extension."
    echo "# Everything else is expected from ${SYSEXT_ID} ${SYSEXT_VERSION_ID}."
    for rpm in "${bundled[@]}"; do
        basename "$rpm"
    done
} > "$STAGE/usr/share/${NAME}/sysext-manifest.txt"

echo "==> extension-release"
mkdir -p "$STAGE/usr/lib/extension-release.d"
# ARCHITECTURE is deliberately absent: systemd only checks it when it is set,
# and everything in here is noarch. Setting it would be a claim the contents do
# not make.
cat > "$STAGE/usr/lib/extension-release.d/extension-release.${IMAGE_NAME}" <<EOF
ID=${SYSEXT_ID}
VERSION_ID=${SYSEXT_VERSION_ID}
SYSEXT_SCOPE=system
SYSEXT_LEVEL=1.0
EOF

echo "==> squashfs"
# -all-root because the extension is merged as root and the build runs as the
# user; without it every file would carry the builder's uid.
mksquashfs "$STAGE" "$IMAGE_OUT" -all-root -noappend -quiet -no-progress

echo
echo "==> built ${IMAGE_OUT} ($(du -h "$IMAGE_OUT" | cut -f1))"
echo "    for ${SYSEXT_ID} ${SYSEXT_VERSION_ID}; systemd will refuse it elsewhere"
echo
echo "install it with:"
echo "    sudo cp ${IMAGE_OUT} /var/lib/extensions/"
echo "    sudo systemd-sysext merge"
