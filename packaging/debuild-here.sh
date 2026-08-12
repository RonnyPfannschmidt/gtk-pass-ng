#!/usr/bin/env bash
# Build the .deb on *this* machine, which must be the Debian or Ubuntu being
# built for.
#
# Not called directly as a rule: build-deb.sh prepares the source tree and then
# runs this, either here or inside a container. CI already runs inside an image
# of the right release, so it takes the direct path; a developer on an ostree
# desktop has no dpkg-buildpackage and takes the container one. Either way the
# build itself is this file, so there is one description of it rather than two
# that drift -- the same arrangement as rpmbuild-here.sh.
#
# Expects: STAGE, a source tree with debian/ in it, prepared by build-deb.sh.
# Writes:  the .deb beside it, which build-deb.sh collects.
set -euo pipefail

: "${STAGE:?set by build-deb.sh}"

# What debian/control declares, minus what is already installed. The container
# image has all of it, so this normally installs nothing and says so; a bare CI
# container has the toolchain from its own apt line and this fills the rest.
if ! dpkg-checkbuilddeps "${STAGE}/debian/control" 2>/dev/null; then
    echo "==> installing build dependencies"
    apt-get update -qq
    # build-essential is the one that is not in debian/control: every Debian
    # source package depends on it implicitly, so nobody writes it down and
    # dpkg-checkbuilddeps asks for it anyway. Left out, the derived list
    # installs cleanly and the build then stops on `build-essential:native`.
    # shellcheck disable=SC2046  # the list is one package per line, by design
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        $("$(dirname "$0")/deb-builddeps.sh" "${STAGE}/debian/control")
fi

cd "$STAGE"

# Binary only. There is no upload and no Debian archive at the other end of
# this: the source package a -S build would produce has nowhere to go, and
# signing it needs a key this has no business asking for.
dpkg-buildpackage --build=binary --no-sign
