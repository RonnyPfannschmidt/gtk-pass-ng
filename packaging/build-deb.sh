#!/usr/bin/env bash
# Build the GTKPass .deb.
#
# The Debian counterpart of build-rpm.sh, and the same shape: work out the
# version from git, build the sdist, and package *that* -- so what is tested is
# the tarball a release publishes rather than the working copy beside it.
#
#   packaging/build-deb.sh                        build for Debian trixie
#   DEB_TARGET=ubuntu:26.04 packaging/build-deb.sh   ... or for Ubuntu
#
# dpkg-buildpackage runs inside a container of that target unless it is already
# running on one, which is CI. The target decides what apt hands the build, and
# that is the whole question a distribution package asks.
#
# Output lands in dist/deb/.
set -euo pipefail

cd "$(dirname "$0")/.."

# Debian trixie is the older of the two targets and the floor: bookworm carries
# GTK 4.8 and the application needs 4.10. Ubuntu 26.04 is the current LTS, and
# the newer end -- GTK 4.22 and libadwaita 1.9 against trixie's 4.18 and 1.7.
#
# Ubuntu 24.04 is deliberately not among them, and the reason is not GTK: its
# setuptools is 68, which cannot parse the PEP 639 `license` field pyproject
# declares and asks setuptools>=77 for. That fails the wheel build itself, so
# no arrangement of the packaging gets around it. See docs/DEBIAN.md.
DEB_TARGET="${DEB_TARGET:-debian:trixie}"

# The distribution field of the changelog entry. Nothing is uploaded anywhere,
# so this is a label rather than a destination.
DEB_SUITE="${DEB_SUITE:-unstable}"

# Named the target, so the version says which release the package was built
# for and the two targets stop producing the same filename. deb-version.sh has
# the reasoning.
read -r UPSTREAM_VERSION DEB_VERSION < <(./packaging/deb-version.sh "$DEB_TARGET")
# The upstream part, which is what the orig tarball has to be named after. The
# revision is everything from the last `-`, target and all: an orig tarball
# belongs to the upstream release, not to the packaging of it, and one named
# after the target would be a different tarball per target for identical bytes.
ORIG_VERSION="${DEB_VERSION%-*}"

case "$DEB_VERSION" in
    *.dirty-*) echo "note: working tree is dirty, building ${DEB_VERSION}" >&2 ;;
esac

echo "==> ${DEB_VERSION} for ${DEB_TARGET}"

rm -rf dist/deb build/deb
mkdir -p dist/deb build/deb

# Without the pretend version setuptools-scm derives one from git describe,
# which for a snapshot is a dev version no Debian version could sort against.
#
# uv is what a developer here has; CI is inside a bare container and has
# python3-build instead. Either produces the same sdist.
#
# --no-isolation there on purpose, and it is not only about the network. An
# isolated build wants python3-venv, which Debian splits out of the interpreter
# and which is absent from every one of these images, and then fetches
# setuptools and setuptools-scm from PyPI -- inside a build whose whole subject
# is what the distribution provides. Both come from apt instead, as
# debian/control asks for them.
if command -v uv >/dev/null; then
    SETUPTOOLS_SCM_PRETEND_VERSION="${UPSTREAM_VERSION}" \
        UV_NO_SYNC=1 uv build --sdist --out-dir dist
else
    SETUPTOOLS_SCM_PRETEND_VERSION="${UPSTREAM_VERSION}" \
        python3 -m build --sdist --no-isolation --outdir dist
fi

# Named for the distribution, gtk-pass-ng, underscored per PEP 625.
sdist="dist/gtk_pass_ng-${UPSTREAM_VERSION}.tar.gz"
[ -f "$sdist" ] || { echo "error: expected sdist at $sdist" >&2; exit 1; }

# The tarball under the name dpkg expects of an upstream release, and the
# source tree unpacked beside it. Nothing is patched: debian/ is the whole of
# the difference between the two, which is what `3.0 (quilt)` with an empty
# patch series means.
cp "$sdist" "build/deb/gtk-pass-ng_${ORIG_VERSION}.orig.tar.gz"
tar -C build/deb -xzf "$sdist"
STAGE="$PWD/build/deb/gtk_pass_ng-${UPSTREAM_VERSION}"
cp -r packaging/debian "$STAGE/debian"

# The changelog's top entry is where dpkg reads the version, and that version
# comes from git -- so it is generated here rather than kept in the tree, where
# it would be wrong from the next commit onwards and wrong quietly. The date is
# the commit's, not today's, so building the same commit twice gives the same
# package; LC_ALL=C because the format wants English day and month names
# whatever locale the person building happens to run in.
changelog_date=$(LC_ALL=C git log -1 --format=%cd --date=rfc2822)
sed -e "s/@VERSION@/${DEB_VERSION}/" \
    -e "s/@SUITE@/${DEB_SUITE}/" \
    -e "s/@DATE@/${changelog_date}/" \
    packaging/debian/changelog.in > "$STAGE/debian/changelog"
rm "$STAGE/debian/changelog.in"

# Build here when this already *is* the target -- which is CI, and anyone
# working on a Debian. Otherwise a container, because the ostree desktops this
# is developed on have no dpkg at all.
if [ -z "${USE_CONTAINER:-}" ]; then
    target_id="${DEB_TARGET%%:*}"
    target_release="${DEB_TARGET#*:}"
    # The tag is a codename on Debian and a number on Ubuntu, so both spellings
    # count as a match. Anything else is a container: building for a target on
    # something that is not it is what produces a package against the wrong
    # Python and the wrong GTK.
    here_id=$(. /etc/os-release 2>/dev/null && echo "${ID:-}")
    here_codename=$(. /etc/os-release 2>/dev/null && echo "${VERSION_CODENAME:-}")
    here_version=$(. /etc/os-release 2>/dev/null && echo "${VERSION_ID:-}")
    if command -v dpkg-buildpackage >/dev/null &&
        [ "$here_id" = "$target_id" ] &&
        { [ "$here_codename" = "$target_release" ] ||
            [ "$here_version" = "$target_release" ]; }; then
        USE_CONTAINER=0
    else
        USE_CONTAINER=1
    fi
fi

if [ "$USE_CONTAINER" = "0" ]; then
    echo "==> dpkg-buildpackage here (${DEB_TARGET})"
    STAGE="$STAGE" packaging/debuild-here.sh
else
    # shellcheck source=packaging/container-runtime.sh
    . "$(dirname "$0")/container-runtime.sh"
    # shellcheck source=packaging/builder-image.sh
    . "$(dirname "$0")/builder-image.sh"
    builder=$(deb_builder_image "docker.io/library/${DEB_TARGET}")
    echo "==> dpkg-buildpackage in ${builder} (${CONTAINER_RUNTIME})"
    "$CONTAINER_RUNTIME" run --rm \
        -v "$PWD:/src:z" \
        -e "STAGE=/src/build/deb/gtk_pass_ng-${UPSTREAM_VERSION}" \
        "$builder" \
        /src/packaging/debuild-here.sh
fi

# dpkg-buildpackage writes beside the source tree, not into it.
mv build/deb/*.deb dist/deb/
# The build metadata too: it records what the package was built against, which
# is the question anyone debugging a package on the wrong release will ask.
mv build/deb/*.buildinfo build/deb/*.changes dist/deb/ 2>/dev/null || true

echo
echo "==> built:"
ls -1 dist/deb/
