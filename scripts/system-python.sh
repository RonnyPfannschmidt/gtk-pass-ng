#!/usr/bin/env bash
# Print the interpreter that carries the distribution's GTK bindings.
#
#   scripts/system-python.sh                       pick one
#   scripts/system-python.sh /usr/bin/python3.13   check that one
#
# PyGObject and pycairo are taken from the distribution rather than built from
# PyPI, so the environment has to be created against an interpreter whose
# site-packages already has them. Which interpreter that is was hardcoded to
# /usr/bin/python3, which is right on most machines and quietly wrong on one
# where the bindings belong to a different minor version. Quietly is the
# problem: `uv venv` succeeds, `uv sync` succeeds, and the answer arrives much
# later as an ImportError from inside the application, or as pycairo trying to
# build from source and failing on headers that are not installed.
#
# So it is asked rather than assumed, and asked the only way that settles it --
# by importing. Absolute paths only: `python3` off PATH is whatever pyenv, conda
# or a uv toolchain has put in front, and a uv-managed interpreter's
# site-packages is precisely the one without the distribution's bindings.
set -uo pipefail

# Two passes rather than one test, because the two are not equally required.
# gi is what the application cannot run without. pycairo is what uv would
# otherwise try to build, and PyGObject has not depended on it for some
# releases -- on a Debian box that followed the documented package list there is
# no python3-cairo at all, python3-gi not pulling one, and rejecting that
# interpreter would refuse to build an environment that works.
PREFERRED='import gi, cairo'
REQUIRED='import gi'

imports() {
    [ -n "$1" ] && [ -x "$1" ] && "$1" -c "$2" >/dev/null 2>&1
}

explain() {
    cat >&2 <<'EOF'
Install your distribution's PyGObject. DEVELOPMENT.md lists the package names;
on Fedora that is

    sudo dnf install python3-gobject gtk4 libadwaita

If it is installed for an interpreter this did not look at, name that one:

    make sync SYSTEM_PYTHON=/usr/bin/python3.13
EOF
}

# An explicitly named one is checked rather than taken on trust: naming the
# wrong interpreter deserves the same answer as having no right one.
if [ "$#" -gt 0 ] && [ -n "$1" ]; then
    if imports "$1" "$REQUIRED"; then
        imports "$1" "$PREFERRED" ||
            echo "$0: note: $1 has no pycairo; nothing here needs one yet" >&2
        echo "$1"
        exit 0
    fi
    echo "$0: $1 cannot import gi" >&2
    explain
    exit 1
fi

# The distribution's own python3 first, because on a machine where it works it
# is the answer, then the versioned ones newest first. The pattern is not
# decoration: /usr/bin/python3.14-config matches a python3.* glob and is not an
# interpreter, and an unmatched glob arrives here as its own literal text.
candidates=(/usr/bin/python3 /usr/local/bin/python3)
versioned=()
for python in /usr/bin/python3.* /usr/local/bin/python3.*; do
    [[ $python =~ /python3\.[0-9]+$ ]] && versioned+=("$python")
done
if [ "${#versioned[@]}" -gt 0 ]; then
    while IFS= read -r python; do
        candidates+=("$python")
    done < <(printf '%s\n' "${versioned[@]}" | sort -Vr)
fi

for wanted in "$PREFERRED" "$REQUIRED"; do
    for python in "${candidates[@]}"; do
        if imports "$python" "$wanted"; then
            echo "$python"
            exit 0
        fi
    done
done

echo "$0: no interpreter found with the GTK bindings" >&2
echo "$0: looked at ${candidates[*]}" >&2
explain
exit 1
