# Build the container the packaging runs in, and say what it is called.
#
# Sourced by build-rpm.sh and build-sysext.sh, which both want the same image
# and neither of which should have to know how it is made, and by build-deb.sh,
# which wants the Debian one. Expects CONTAINER_RUNTIME to be set already --
# container-runtime.sh does that.
#
#   builder=$(builder_image 44)
#   builder=$(deb_builder_image docker.io/library/debian:trixie)
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

# The same thing for Debian and Ubuntu, which are one image with two bases
# rather than two images: what differs between them is what apt hands out, and
# that is exactly what the package is being built to find out.
#
# The tag is derived from the base image so the two targets cannot share a
# cached image and quietly build for each other.
deb_builder_image() {
    local base=$1
    local tag="localhost/gtkpass-build-deb:$(echo "$base" | tr ':/' '--')"

    if [ -n "${GTKPASS_BUILDER_IMAGE:-}" ]; then
        echo "$GTKPASS_BUILDER_IMAGE"
        return 0
    fi

    echo "==> preparing ${tag} (cached unless the toolchain changed)" >&2
    "$CONTAINER_RUNTIME" build \
        --quiet \
        --build-arg "BASE_IMAGE=${base}" \
        --tag "$tag" \
        --file packaging/Containerfile.build.deb \
        . >&2

    echo "$tag"
}
