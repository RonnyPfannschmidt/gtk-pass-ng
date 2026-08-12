#!/usr/bin/env bash
# What version the Debian package of the checkout in the current directory is.
#
#   $ packaging/deb-version.sh
#   0.1.0 0.1.0~git20260812.3d35ac9-1
#   $ packaging/deb-version.sh debian:trixie
#   0.1.0 0.1.0~git20260812.3d35ac9-1~debian.trixie
#
# Two words: the upstream version -- the release this is, or is a snapshot of,
# and the version the sdist and the wheel inside are built as -- and the Debian
# version, which carries the commit, and the target when it is given one.
#
# Its own script rather than a paragraph inside build-deb.sh, because the thing
# worth checking here is an ordering, and an ordering can only be checked by
# producing several versions and comparing them. tests/test_deb_packaging.py
# does that against dpkg itself, in a throwaway repository standing in each of
# the three states below.
#
# Those states are the ones build-rpm.sh handles, and the point is the same:
# upgrades have to go in the right direction. dpkg's spelling of it is not
# rpm's, though. `~` sorts before nothing at all, so it marks a snapshot of a
# release that has not happened; `+` sorts after, so it marks work built on top
# of one that has. Getting those two the wrong way round produces a package
# that installs, runs, and then declines to be upgraded by the actual release.
#
# Deliberately does not cd anywhere: it answers for the current directory.
set -euo pipefail

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "error: not a git checkout, so there is no version to derive" >&2
    exit 1
fi

# The commit's own date, not today's, so building the same commit twice gives
# the same package.
commit_date=$(git log -1 --format=%cd --date=format:%Y%m%d)
commit_hash=$(git rev-parse --short HEAD)
snapshot="git${commit_date}.${commit_hash}"

# A tree with uncommitted changes does not describe the commit it names.
dirty=0
if ! git diff --quiet HEAD; then
    dirty=1
    snapshot="${snapshot}.dirty"
fi

if tag=$(git describe --exact-match --tags HEAD 2>/dev/null); then
    upstream="${tag#v}"
    if [ "$dirty" = 1 ]; then
        # Standing on a tag is not the same as being it: this is that release
        # plus uncommitted changes, and sorts after it accordingly.
        version="${upstream}+${snapshot}"
    else
        version="${upstream}"
    fi
elif previous=$(git describe --abbrev=0 --tags HEAD 2>/dev/null); then
    # After a tag: work since that release, so it sorts after it and before
    # whatever comes next.
    upstream="${previous#v}"
    version="${upstream}+${snapshot}"
else
    # Before any tag has ever been made: a snapshot of the release to come, so
    # it must sort *before* it, and the eventual 0.1.0-1 upgrades over this.
    upstream="0.1.0"
    version="${upstream}~${snapshot}"
fi

# -1 throughout: there is one packaging of each of these, and it is this one.
#
# Followed by the target, when a build names one. Two targets produce two
# different packages -- dh_python3 writes the interpreter's dependencies out of
# whatever apt hands it, so trixie's are not Ubuntu's -- and both are
# Architecture: all, so without this they are two files with the same name. In
# a job each has an artefact to itself and nothing notices; a release collects
# every artefact into one directory, and there the second replaces the first
# without a word. The RPM has carried its %{dist} tag from the start, and this
# is that fact in dpkg's spelling.
#
# `~` again, so a package out of a real archive supersedes one of these. That is
# the convention for a build made outside the archive, and here it is also true:
# nothing this produces comes from one.
#
# A colon cannot appear in a Debian version -- that is the epoch separator -- so
# debian:trixie is spelled debian.trixie.
target="${1:-}"
if [ -n "$target" ]; then
    echo "${upstream} ${version}-1~${target//:/.}"
else
    echo "${upstream} ${version}-1"
fi
