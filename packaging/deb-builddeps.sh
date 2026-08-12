#!/usr/bin/env bash
# Name the packages a Debian build of this project needs, one per line.
#
#   $ packaging/deb-builddeps.sh
#   debhelper
#   dh-python
#   ...
#
# Read out of debian/control rather than typed out again, for the reason
# buildreqs-from-pyproject.py exists on the Fedora side: a second copy of a
# dependency list goes stale quietly, and shows up only as a build that
# installs things it was supposed to have already.
#
# Two users, which is the point. packaging/Containerfile.build.deb installs
# this when it prepares the image, so a build inside it installs nothing; and
# debuild-here.sh installs whatever is still missing, which is what a bare CI
# container needs.
#
# Not a full dependency parser. It resolves the fields this control file
# actually uses -- version constraints, alternatives, architecture and profile
# qualifiers -- and if a future one needs more than that, the build fails
# loudly on a missing package rather than quietly on a wrong one.
set -euo pipefail

control="${1:-$(dirname "$0")/debian/control}"

awk '
    /^Build-Depends:/ { collecting = 1; sub(/^Build-Depends:/, ""); print; next }
    collecting && /^[ \t]/ { print; next }
    collecting { exit }
' "$control" |
    tr ',' '\n' |
    sed -e 's/|.*//' -e 's/([^)]*)//g' -e 's/\[[^]]*\]//g' -e 's/<[^>]*>//g' \
        -e 's/[[:blank:]]//g' |
    grep -v '^$' |
    # The one name that is not a package: debhelper-compat is a virtual
    # package, declared this way because the compatibility level is a version
    # of it. What you install is debhelper.
    sed -e 's/^debhelper-compat$/debhelper/'
