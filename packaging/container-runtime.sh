# Pick the container runtime, for the build scripts to source.
#
# podman first, because that is what the Fedora and ostree desktops this is
# aimed at ship, and because it needs no daemon and no group membership that
# amounts to root. docker is accepted because plenty of machines have only that,
# and the two agree on every flag used here.
#
# Sets CONTAINER_RUNTIME. Honours it if already set, so an unusual setup can
# name its own without editing anything.

if [ -z "${CONTAINER_RUNTIME:-}" ]; then
    for _candidate in podman docker; do
        if command -v "$_candidate" >/dev/null 2>&1; then
            CONTAINER_RUNTIME=$_candidate
            break
        fi
    done
    unset _candidate
fi

if [ -z "${CONTAINER_RUNTIME:-}" ]; then
    echo "error: no container runtime found; install podman, or set" >&2
    echo "       CONTAINER_RUNTIME to one that takes podman's arguments." >&2
    echo "       On a Fedora that already has rpm-build, USE_CONTAINER=0" >&2
    echo "       builds directly instead and needs no runtime at all." >&2
    exit 1
fi
