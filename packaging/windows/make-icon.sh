#!/usr/bin/env bash
# Render the application icon to the .ico Windows insists on.
#
# Windows takes its icons from the executable's resources and from the entries
# an installer writes, and both want a .ico -- there is no arrangement under
# which the SVG in data/icons is enough. So the result is committed, next to the
# scalable original, and this is how it is regenerated when that original
# changes.
#
# A single 256x256 image is not enough either: Windows scales an icon down for
# the taskbar and the small file lists, and a downscaled 256 loses the strokes
# in a symbolic-style icon. Each size below is rendered from the vector.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)

app_id=io.github.RonnyPfannschmidt.GTKPass
source=$repo/data/icons/hicolor/scalable/apps/$app_id.svg
target=$repo/data/icons/$app_id.ico

for tool in rsvg-convert magick; do
    command -v "$tool" >/dev/null || {
        echo "$tool is needed to render the icon and was not found" >&2
        exit 1
    }
done

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

sizes=(16 24 32 48 64 128 256)
rendered=()
for size in "${sizes[@]}"; do
    rsvg-convert --width "$size" --height "$size" \
        --output "$work/$size.png" "$source"
    rendered+=("$work/$size.png")
done

magick "${rendered[@]}" "$target"

echo "wrote $target"
