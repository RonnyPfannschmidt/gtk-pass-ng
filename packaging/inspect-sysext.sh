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
