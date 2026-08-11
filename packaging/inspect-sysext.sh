#!/usr/bin/env bash
# Check a built sysext image without merging it.
#
#   packaging/inspect-sysext.sh dist/sysext/gtkpass-bluefin-44.raw
#
# CI runs this because it cannot do the real thing: systemd-sysext needs a
# running systemd and a writable /run, and a container has neither. What can be
# checked from outside is that the image claims the right target, carries only
# what a sysext may carry, and does not ship any of the merged caches that would
# take the desktop's own settings or icons away with it.
#
# packaging/test-sysext.sh is the one that actually merges.
set -euo pipefail

image=${1:-}
[ -n "$image" ] || { echo "usage: $0 <image.raw>" >&2; exit 1; }
[ -f "$image" ] || { echo "error: no such image: $image" >&2; exit 1; }

fail() { echo "FAIL: $*" >&2; exit 1; }

# systemd takes the name from the image file itself: the release file inside
# has to be extension-release.$IMAGE, where $IMAGE is this basename. Getting
# that wrong is invisible from the contents -- the image is a perfectly good
# squashfs -- and shows up only as "No medium found" at merge time.
image_name=$(basename "$image" .raw)
release_path="usr/lib/extension-release.d/extension-release.${image_name}"

listing=$(unsquashfs -ll "$image")
grep -q " squashfs-root/${release_path}$" <<<"$listing" \
    || fail "no ${release_path}; systemd will refuse this image outright"
release=$(unsquashfs -cat "$image" "$release_path")

echo "==> $(basename "$image") ($(du -h "$image" | cut -f1))"
echo "$release" | sed 's/^/    /'

echo "==> it names a target"
grep -q '^ID=' <<<"$release" || fail "extension-release has no ID"
# The check systemd would otherwise skip. An image that merges anywhere is an
# image that was tested nowhere; see docs/PACKAGING.md.
if grep -q '^ID=_any$' <<<"$release"; then
    fail "ID=_any would merge onto any system"
fi
grep -q '^SYSEXT_SCOPE=' <<<"$release" || fail "extension-release has no scope"

echo "==> it carries only /usr"
while read -r entry; do
    case "$entry" in
        squashfs-root|squashfs-root/usr|squashfs-root/usr/*|squashfs-root/opt|squashfs-root/opt/*) ;;
        "") ;;
        *) fail "outside /usr and /opt: ${entry#squashfs-root/}" ;;
    esac
done < <(awk '{print $NF}' <<<"$listing")

echo "==> it carries its own SELinux labels"
# A merged directory takes its attributes from the layer above, so the image's
# usr/lib is what SELinux sees for /usr/lib on the whole system while this is
# merged -- and on a Fedora ostree that is where the system users live. An image
# labelled by the build machine instead of by the policy takes dnsmasq and the
# NetworkManager dispatcher scripts down with it. Issue #23, and build-sysext.sh
# says the rest.
xattr_ids=$(unsquashfs -s "$image" | awk '/Number of xattr ids/ { print $NF }')
[ "${xattr_ids:-0}" -gt 0 ] \
    || fail "the image carries no xattrs, so every path in it is unlabelled"

# Reading the values back means writing security.* xattrs somewhere, which
# unsquashfs will only attempt as root -- and which the kernel will only allow
# where SELinux is enabled. A user namespace covers the first half on a normal
# machine; a CI container with no SELinux at all cannot do it, and says so
# rather than reporting a check it did not make.
labels=$(mktemp -d)
trap 'rm -rf "$labels"' EXIT
# Reading the value out of getfattr's own output rather than with
# --only-values: the kernel returns a label with its terminating NUL, which a
# command substitution strips with a warning on every file. Nothing here may end
# in `head` either -- this script runs under pipefail, and the SIGPIPE that a
# closed pipe sends the reader upstream would turn into a silent fallback to the
# weaker check below.
extracted_context() {
    getfattr -n security.selinux --absolute-names "$1" 2>/dev/null \
        | sed -n 's/^security\.selinux="\(.*\)"$/\1/p'
}

if unshare -Ur unsquashfs -no-progress -x -d "$labels/root" "$image" >/dev/null 2>&1 \
    && lib_context=$(extracted_context "$labels/root/usr/lib") \
    && [ -n "$lib_context" ]
then
    echo "    usr/lib is ${lib_context}"
    # The type, not the level: a confined domain is refused on the type, and a
    # policy that ranges the level would fail an s0 check while being right.
    case "$lib_context" in
        *:lib_t:*) ;;
        *) fail "usr/lib is ${lib_context}, not lib_t; merging this relabels the host's" ;;
    esac

    # Whatever the extraction directory itself carries is what an unlabelled
    # path in the image comes out as, having taken the label of where it landed
    # rather than one of its own. Comparing against that rather than naming a
    # type keeps this true wherever TMPDIR points. The image's own root is
    # exempt: it is above the directory systemd overlays, and is never merged.
    unlabelled=$(
        getfattr -R -n security.selinux --absolute-names "$labels/root" 2>/dev/null \
            | awk -v marker="security.selinux=\"$(extracted_context "$labels")\"" \
                  -v root="$labels/root" '
                /^# file: / { path = substr($0, 9); next }
                $0 == marker && path != root { print substr(path, length(root) + 2) }
            '
    )
    if [ -n "$unlabelled" ]; then
        printf '%s\n' "$unlabelled" | sed -n '1,5s/^/    /p' >&2
        fail "those paths carry no label of their own in the image"
    fi
else
    echo "    (labels cannot be read back here; only their presence was checked)"
fi

echo "==> it ships no merged cache"
# Each of these is a single file holding every application's entries. An
# overlay carrying its own copy hides the host's rather than adding to it, so
# the desktop loses its settings, or its icons, on merge.
for cache in \
    usr/share/glib-2.0/schemas/gschemas.compiled \
    usr/share/icons/hicolor/icon-theme.cache \
    usr/share/applications/mimeinfo.cache
do
    if grep -q " squashfs-root/${cache}$" <<<"$listing"; then
        fail "ships ${cache}"
    fi
done

echo "==> the schema is compiled somewhere private"
grep -q " squashfs-root/usr/share/gtkpass/schemas/gschemas.compiled$" <<<"$listing" \
    || fail "no private schema cache; the application will not find its settings"

echo "==> what it vendored"
unsquashfs -cat "$image" "usr/share/${NAME:-gtkpass}/sysext-manifest.txt" \
    2>/dev/null | grep -v '^#' | sed 's/^/    /' \
    || fail "no manifest; cannot tell what this image carries"

# The vendoring set is resolved against whatever built this, so a build on the
# wrong base silently bundles the desktop's own stack -- GTK, libadwaita,
# PyGObject -- and still produces a working image. It is working for the wrong
# reason: the application would then run against a GTK the desktop is not using.
# Size is the cheapest signal that this happened; the real content is pure
# Python and data and comes to a few hundred kilobytes.
size_kb=$(du -k "$image" | cut -f1)
limit_kb=${SYSEXT_SIZE_LIMIT_KB:-8192}
echo "    image is ${size_kb} KiB (ceiling ${limit_kb})"
[ "$size_kb" -le "$limit_kb" ] \
    || fail "image is far larger than pure Python and data; check what it vendored"

echo "==> the application is in there"
for path in \
    usr/bin/gtkpass \
    usr/share/applications/io.github.RonnyPfannschmidt.GTKPass.desktop \
    usr/share/metainfo/io.github.RonnyPfannschmidt.GTKPass.metainfo.xml
do
    grep -q " squashfs-root/${path}$" <<<"$listing" || fail "missing ${path}"
done

# The .ui files are read through importlib.resources at run time and are missing
# nowhere else; without them the application dies on the first template import.
grep -q "squashfs-root/usr/lib/python3.*/site-packages/gtkpass/ui/blueprints/window.ui$" \
    <<<"$listing" || fail "the compiled Blueprint files did not travel"

echo
echo "==> image looks sound"
