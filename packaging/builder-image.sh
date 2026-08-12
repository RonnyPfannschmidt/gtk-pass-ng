# Build the container the packaging runs in, and say what it is called.
#
# Sourced by build-rpm.sh and build-sysext.sh, which both want the same image
# and neither of which should have to know how it is made. Expects
# CONTAINER_RUNTIME to be set already -- container-runtime.sh does that.
#
#   builder=$(builder_image 44)
#
# The build is the staleness check. Every layer of Containerfile.build is
# cached by the runtime and keyed on its inputs, so a run that changes nothing
# takes about a second and a change to the spec rebuilds from there down.
# Nothing here has a stamp file to keep in step with anything.
#
# GTKPASS_BUILDER_IMAGE names an image to use as-is, for CI that has one
# prepared or for a machine that would rather not build one.

builder_image() {
    local release=$1
    local tag="localhost/gtkpass-build:fc${release}"

    if [ -n "${GTKPASS_BUILDER_IMAGE:-}" ]; then
        echo "$GTKPASS_BUILDER_IMAGE"
        return 0
    fi

    # To stderr: the caller is reading stdout for the image name.
    echo "==> preparing ${tag} (cached unless the toolchain changed)" >&2
    "$CONTAINER_RUNTIME" build \
        --quiet \
        --build-arg "FEDORA_RELEASE=${release}" \
        --tag "$tag" \
        --file packaging/Containerfile.build \
        . >&2

    echo "$tag"
}
