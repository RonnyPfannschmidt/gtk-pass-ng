#!/usr/bin/env bash
# Build the GTKPass RPM.
#
# rpmbuild runs in a Fedora container rather than on this machine: the target is
# an ostree desktop, where layering rpm-build in order to package something is a
# reboot and a permanent addition to the image. The container also pins which
# Fedora the package is built for, which decides the Python version its files
# land under -- a package built against python3.13 installs nothing importable
# on a python3.14 host.
#
#   packaging/build-rpm.sh                    build for the running system
#   FEDORA_RELEASE=43 packaging/build-rpm.sh  build for another Fedora
#
# Output lands in dist/rpm/.
set -euo pipefail

cd "$(dirname "$0")/.."

# The commit's own date, not today's, so building the same commit twice gives
# the same package.
commit_date=$(git log -1 --format=%cd --date=format:%Y%m%d)
commit_hash=$(git rev-parse --short HEAD)
SNAPSHOT="${commit_date}git${commit_hash}"

# A tree with uncommitted changes does not describe the commit it names.
if ! git diff --quiet HEAD; then
    SNAPSHOT="${SNAPSHOT}.dirty"
    echo "note: working tree is dirty, building ${SNAPSHOT}" >&2
fi

# Version and release come from git, in the three states a checkout can be in.
# The point of the Release forms is that upgrades work in the right direction:
# rpm sorts 0.1.<snap> before 1, and 2.<snap> after it.
if tag=$(git describe --exact-match --tags HEAD 2>/dev/null); then
    # On a tag: this is that release.
    VERSION="${tag#v}"
    RELEASE=1
elif previous=$(git describe --abbrev=0 --tags HEAD 2>/dev/null); then
    # After a tag: a snapshot of work since it, so it must sort *after* the
    # release it is named for, or an upgrade would go backwards onto it.
    VERSION="${previous#v}"
    RELEASE="2.${SNAPSHOT}"
else
    # Before any tag has ever been made: a snapshot of the release to come, so
    # it must sort before it, and the eventual 0.1.0-1 upgrades over this.
    VERSION=0.1.0
    RELEASE="0.1.${SNAPSHOT}"
fi

# VERSION_ID rather than ID, because the derivatives this is aimed at --
# Bluefin, Silverblue, Bazzite -- report their own ID and Fedora's release.
if [ -z "${FEDORA_RELEASE:-}" ]; then
    FEDORA_RELEASE=$(. /etc/os-release && echo "${VERSION_ID%%.*}")
fi

IMAGE="registry.fedoraproject.org/fedora:${FEDORA_RELEASE}"

echo "==> ${VERSION}-${RELEASE}"
rm -rf dist/rpm
mkdir -p dist/rpm
# Without this setuptools-scm derives a version from git describe, which with no
# tags in the repository is a dev version no RPM Release could sort against.
#
# uv is what a developer here has; CI is inside a bare Fedora container and has
# python3-build instead. Either produces the same sdist.
if command -v uv >/dev/null; then
    SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION}" uv build --sdist --out-dir dist
else
    SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION}" \
        python3 -m build --sdist --outdir dist
fi

# Named for the distribution, gtk-pass, underscored per PEP 625.
sdist="dist/gtk_pass-${VERSION}.tar.gz"
[ -f "$sdist" ] || { echo "error: expected sdist at $sdist" >&2; exit 1; }

# Build here when this already *is* the Fedora being built for -- which is CI,
# and anyone running a package-based Fedora. Otherwise a container, because the
# ostree desktops this is developed on have no rpm-build and layering it to
# package something is a reboot.
if [ -z "${USE_CONTAINER:-}" ]; then
    if [ "$(. /etc/os-release && echo "${VERSION_ID%%.*}")" = "$FEDORA_RELEASE" ] \
        && command -v rpmbuild >/dev/null; then
        USE_CONTAINER=0
    else
        USE_CONTAINER=1
    fi
fi

if [ "$USE_CONTAINER" = "0" ]; then
    echo "==> rpmbuild here (fedora ${FEDORA_RELEASE})"
    VERSION="$VERSION" RELEASE="$RELEASE" SRC="$PWD" packaging/rpmbuild-here.sh
else
    # shellcheck source=packaging/container-runtime.sh
    . "$(dirname "$0")/container-runtime.sh"
    echo "==> rpmbuild in ${IMAGE} (${CONTAINER_RUNTIME})"
    "$CONTAINER_RUNTIME" run --rm \
        -v "$PWD:/src:z" \
        -e "VERSION=${VERSION}" \
        -e "RELEASE=${RELEASE}" \
        -e "SRC=/src" \
        "$IMAGE" \
        /src/packaging/rpmbuild-here.sh
fi

echo
echo "==> built:"
ls -1 dist/rpm/
