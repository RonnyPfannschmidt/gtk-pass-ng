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
# The SELinux label of every path in the image, computed rather than copied off
# the build machine. See the file contexts step below for why.
PSEUDO="${STAGE}.pseudo"

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
        # The prepared image, which already has the download plugin. This used
        # to start a bare Fedora per capability and install dnf-plugins-core in
        # each of them -- some thirty packages, downloaded again every time,
        # for one file.
        # shellcheck source=packaging/container-runtime.sh
        . "$(dirname "$0")/container-runtime.sh"
        # shellcheck source=packaging/builder-image.sh
        . "$(dirname "$0")/builder-image.sh"
        local builder
        builder=$(builder_image "$FEDORA_RELEASE")
        "$CONTAINER_RUNTIME" run --rm -v "$PWD/dist/sysext:/out:z" \
            "$builder" \
            bash -euo pipefail -c "cd /out && dnf download '${capability}' >/dev/null"
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
rm -rf "$STAGE" "$IMAGE_OUT" "$PSEUDO"
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

echo "==> file contexts"
# The SELinux label of every path, worked out from the target's policy and
# written into the image, rather than whatever the build machine happened to
# label the staging tree.
#
# This is not a detail of the extension's own files. systemd-sysext merges with
# an overlay, and a merged directory takes its attributes from the layer above --
# so the image's usr/lib decides what SELinux sees for /usr/lib on the *whole
# system* while the extension is merged. On a Fedora ostree that is where the
# package-created system users live, because /etc has to stay mergeable, and
# nss-altfiles reads them from there. Label it wrong and every confined service
# loses the ability to look up its own user: dnsmasq exits with "unknown user or
# group: dnsmasq", the NetworkManager dispatcher scripts all exit 126. An
# extension has to carry usr/lib/extension-release.d to be an extension at all,
# so no sysext escapes this, whatever else it ships. Issue #23.
#
# It is easy to misdiagnose, too: an interactive shell is unconfined and *is*
# allowed to search the wrong label, so `getent passwd dnsmasq` answers happily
# while dnsmasq itself cannot.
#
# Nothing here may be left to the build filesystem. Building in a container
# gives the tree container_file_t (podman's :z relabels the volume, and the
# staged files inherit it); building on a runner with no SELinux gives it no
# label at all. mksquashfs stores xattrs by default, so either one travels.
# Computing the labels instead is also the only approach that works in both
# places -- a runner with no SELinux cannot write a security.selinux xattr to
# its own filesystem at all, so `setfiles` on the staging tree is not an option
# there.
FILE_CONTEXTS="${SYSEXT_FILE_CONTEXTS:-/etc/selinux/targeted/contexts/files/file_contexts}"
if [ ! -f "$FILE_CONTEXTS" ]; then
    echo "error: no file_contexts at ${FILE_CONTEXTS}." >&2
    echo "       Install selinux-policy-targeted, or name another file with" >&2
    echo "       SYSEXT_FILE_CONTEXTS=. Building without it would ship an" >&2
    echo "       unlabelled image, which relabels the host's /usr/lib on merge." >&2
    exit 1
fi
if ! command -v matchpathcon >/dev/null; then
    echo "error: matchpathcon is not installed (libselinux-utils)." >&2
    exit 1
fi

# A pseudo definition is whitespace-separated, so a path containing a space
# cannot be written as one. Nothing vendored so far has one; a package that did
# would otherwise get a definition for a path that does not exist and no label
# for the one that does.
if [ -n "$(find "$STAGE" -name '* *' -print -quit)" ]; then
    echo "error: a staged path contains whitespace, which a pseudo file cannot" >&2
    echo "       express. $(find "$STAGE" -name '* *' -print -quit)" >&2
    exit 1
fi

# Anything that is not a directory, a regular file or a symlink has no business
# in a sysext, and would go unlabelled below rather than being noticed.
if [ -n "$(find "$STAGE" -mindepth 1 ! -type d ! -type f ! -type l -print -quit)" ]; then
    echo "error: $(find "$STAGE" -mindepth 1 ! -type d ! -type f ! -type l -print -quit)" \
        "is not a file, directory or symlink" >&2
    exit 1
fi

# matchpathcon answers for the path a file will have on the target, which is
# not where it is staged -- hence the leading slash on the lookup and the
# staged-relative name in the definition. -m names the kind of file, so the
# lookup is decided by the policy alone; without it matchpathcon stat()s the
# builder's own filesystem to guess, and answers about the build machine's
# /usr/lib rather than about the image's.
emit_contexts() {
    local mode=$1 findtype=$2 path answers index
    local -a staged=() contexts=()
    while IFS= read -r path; do
        staged+=("$path")
    done < <(find "$STAGE" -mindepth 1 -type "$findtype" -printf '%P\n')
    [ ${#staged[@]} -gt 0 ] || return 0

    # Taken as a whole and checked, rather than read straight into the loop
    # below: matchpathcon that cannot parse the policy answers for nothing, and
    # a pipe would turn that into a pseudo file quietly missing those paths.
    if ! answers=$(matchpathcon -m "$mode" -f "$FILE_CONTEXTS" -n "${staged[@]/#//}"); then
        echo "error: matchpathcon could not answer from ${FILE_CONTEXTS}" >&2
        return 1
    fi
    while IFS= read -r path; do
        contexts+=("$path")
    done <<< "$answers"

    # One answer per path, in the order they were asked -- the definitions are
    # paired up by position, so answers going missing would not leave paths
    # unlabelled, it would label them with each other's contexts.
    if [ "${#contexts[@]}" -ne "${#staged[@]}" ]; then
        echo "error: matchpathcon answered for ${#contexts[@]} of ${#staged[@]}" \
            "${mode} paths" >&2
        return 1
    fi

    for index in "${!staged[@]}"; do
        echo "${staged[index]} x security.selinux=${contexts[index]}"
    done
}

{
    emit_contexts dir d
    emit_contexts file f
    emit_contexts lnk_file l
} > "$PSEUDO"

# Every path, or the ones left out are unlabelled in the image and land on the
# filesystem's default rather than on anything the policy chose.
staged_count=$(find "$STAGE" -mindepth 1 | wc -l)
labelled_count=$(wc -l < "$PSEUDO")
if [ "$staged_count" -ne "$labelled_count" ]; then
    echo "error: ${labelled_count} of ${staged_count} staged paths got a label" >&2
    exit 1
fi

# The one the host's services depend on, checked by name rather than trusted.
# On the type alone: the level is not what a confined domain is refused on, and
# a policy that ranges it (an MLS one, or a file_contexts named through
# SYSEXT_FILE_CONTEXTS) would fail a check that insisted on s0 while being
# perfectly correct.
lib_context=$(sed -n 's/^usr\/lib x security\.selinux=//p' "$PSEUDO")
case "$lib_context" in
    *:lib_t:*) ;;
    *)
        echo "error: usr/lib would be labelled '${lib_context}', not lib_t." >&2
        echo "       Merging that relabels the host's /usr/lib; see issue #23." >&2
        exit 1
        ;;
esac
echo "    usr/lib is ${lib_context}, from $(basename "$FILE_CONTEXTS")"

# mksquashfs gives hardlinked files a single shared xattr set, so two names for
# one inode that want different labels both silently take whichever was written
# last. The hardlinks an RPM brings are duplicate .pyc files next to each other,
# which want the same label anyway -- but a vendored package that linked across
# directories would produce a mislabelled image that looks perfectly built.
conflicting=$(
    awk '
        NR == FNR {
            split($0, field, " x security.selinux=")
            context[field[1]] = field[2]
            next
        }
        {
            if ($1 in seen && seen[$1] != context[$2]) print $2
            seen[$1] = context[$2]
        }
    ' "$PSEUDO" <(find "$STAGE" -mindepth 1 -type f -links +1 -printf '%i %P\n')
)
if [ -n "$conflicting" ]; then
    echo "error: hardlinked files want different labels, and squashfs can only" >&2
    echo "       hold one for both:" >&2
    echo "$conflicting" | sed 's/^/       /' >&2
    exit 1
fi

echo "==> squashfs"
# -all-root because the extension is merged as root and the build runs as the
# user; without it every file would carry the builder's uid.
#
# -xattrs-exclude drops the staging tree's own SELinux labels, and is not
# optional: mksquashfs refuses outright ("Duplicate xattr name security.selinux")
# when a pseudo definition names an xattr the file already carries, so on any
# builder that labelled the tree this would fail rather than override.
mksquashfs "$STAGE" "$IMAGE_OUT" -all-root -noappend -quiet -no-progress \
    -xattrs-exclude '^security\.selinux' -pf "$PSEUDO"

echo
echo "==> built ${IMAGE_OUT} ($(du -h "$IMAGE_OUT" | cut -f1))"
echo "    for ${SYSEXT_ID} ${SYSEXT_VERSION_ID}; systemd will refuse it elsewhere"
echo
echo "install it with:"
echo "    sudo cp ${IMAGE_OUT} /var/lib/extensions/"
echo "    sudo systemd-sysext merge"
