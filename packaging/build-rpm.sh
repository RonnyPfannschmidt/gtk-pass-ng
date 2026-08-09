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

# The version the spec declares. There is no tag to derive one from, so the
# sdist is pinned to it and the commit goes into Release instead.
VERSION=0.1.0

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

# VERSION_ID rather than ID, because the derivatives this is aimed at --
# Bluefin, Silverblue, Bazzite -- report their own ID and Fedora's release.
if [ -z "${FEDORA_RELEASE:-}" ]; then
    FEDORA_RELEASE=$(. /etc/os-release && echo "${VERSION_ID%%.*}")
fi

IMAGE="registry.fedoraproject.org/fedora:${FEDORA_RELEASE}"

echo "==> sdist ${VERSION} (snapshot ${SNAPSHOT})"
rm -rf dist/rpm
mkdir -p dist/rpm
# Without this setuptools-scm derives a version from git describe, which with no
# tags in the repository is a dev version no RPM Release could sort against.
SETUPTOOLS_SCM_PRETEND_VERSION="${VERSION}" \
    uv build --sdist --out-dir dist

sdist="dist/gtkpass-${VERSION}.tar.gz"
[ -f "$sdist" ] || { echo "error: expected sdist at $sdist" >&2; exit 1; }

echo "==> rpmbuild in ${IMAGE}"
podman run --rm \
    -v "$PWD:/src:z" \
    -e "SNAPSHOT=${SNAPSHOT}" \
    -e "VERSION=${VERSION}" \
    "$IMAGE" \
    bash -euo pipefail -c '
        dnf -y --setopt=install_weak_deps=False install \
            rpm-build rpmdevtools python3-devel pyproject-rpm-macros \
            desktop-file-utils libappstream-glib glib2-devel >/dev/null

        rpmdev-setuptree
        cp "/src/dist/gtkpass-${VERSION}.tar.gz" ~/rpmbuild/SOURCES/

        spec=/src/packaging/gtkpass.spec
        define="--define=snapshot ${SNAPSHOT}"

        dnf -y builddep --spec "$spec" >/dev/null

        # %pyproject_buildrequires reports the project metadata dependencies by
        # failing the source build with exit 11 and writing them into a
        # buildreqs.nosrc.rpm. Install those and go round again; twice is enough
        # in practice, and the bound stops a loop if it is not.
        for _ in 1 2 3; do
            if rpmbuild -br --nodeps "$define" "$spec"; then break; fi
            dnf -y builddep ~/rpmbuild/SRPMS/gtkpass-*.buildreqs.nosrc.rpm >/dev/null
        done

        rpmbuild -ba "$define" "$spec"

        cp ~/rpmbuild/RPMS/noarch/*.rpm /src/dist/rpm/
        cp ~/rpmbuild/SRPMS/gtkpass-*.src.rpm /src/dist/rpm/
    '

echo
echo "==> built:"
ls -1 dist/rpm/
