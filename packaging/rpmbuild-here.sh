#!/usr/bin/env bash
# Build the RPM on *this* machine, which must be the Fedora being built for.
#
# Not called directly as a rule: build-rpm.sh prepares the sdist and then runs
# this, either here or inside a container. CI already runs inside a Fedora of
# the right release, so it takes the direct path; a developer on an ostree
# desktop has no rpm-build and takes the container one. Either way the build
# itself is this file, so there is one description of it rather than two that
# drift.
#
# Expects: dist/gtkpass-$VERSION.tar.gz, $VERSION, $SNAPSHOT, and dnf.
# Writes:  dist/rpm/
set -euo pipefail

: "${VERSION:?set by build-rpm.sh}"
: "${SNAPSHOT:?set by build-rpm.sh}"

SRC="${SRC:-$(cd "$(dirname "$0")/.." && pwd)}"
spec="${SRC}/packaging/gtkpass.spec"
define="--define=snapshot ${SNAPSHOT}"

dnf -y --setopt=install_weak_deps=False install \
    rpm-build rpmdevtools python3-devel pyproject-rpm-macros \
    desktop-file-utils libappstream-glib glib2-devel >/dev/null

rpmdev-setuptree
cp "${SRC}/dist/gtkpass-${VERSION}.tar.gz" ~/rpmbuild/SOURCES/

dnf -y builddep --spec "$spec" >/dev/null

# %pyproject_buildrequires reports the project metadata dependencies by failing
# the source build with exit 11 and writing them into a buildreqs.nosrc.rpm.
# Install those and go round again. One extra pass is enough in practice; three
# attempts is the bound that stops this looping if it ever is not.
for _ in 1 2 3; do
    if rpmbuild -br --nodeps "$define" "$spec"; then break; fi
    dnf -y builddep ~/rpmbuild/SRPMS/gtkpass-*.buildreqs.nosrc.rpm >/dev/null
done

rpmbuild -ba "$define" "$spec"

mkdir -p "${SRC}/dist/rpm"
cp ~/rpmbuild/RPMS/noarch/*.rpm "${SRC}/dist/rpm/"
cp ~/rpmbuild/SRPMS/gtkpass-*.src.rpm "${SRC}/dist/rpm/"
