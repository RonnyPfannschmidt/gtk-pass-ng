#!/usr/bin/env bash
# Render the application icon to the .ico Windows insists on.
#
# Windows takes its icons from the executable's resources and from the entries
# an installer writes, and both want a .ico. There is no vector option: an icon
# resource holds raster images and nothing else, whatever the source artwork
# was. So the result is committed, next to the scalable original, and this is
# how it is regenerated when that original changes.
#
# Each size is rendered from the vector rather than scaled down from one large
# raster. Windows picks a size by context -- 16 in a title bar, 32 in the
# taskbar, 256 in the large icon view -- and a downscaled 256 loses the strokes
# in a symbolic-style icon at the sizes that are seen most.
#
# The images go in **PNG-compressed**, which is what keeps the file at some 17
# kilobytes rather than 370. An .ico entry may hold either a raw bitmap or a
# whole PNG file, and a 256x256 raw entry alone is 270 KB of uncompressed BGRA;
# ImageMagick writes raw by default, which is what the first version of this
# file did. Windows has read PNG entries since Vista, PyInstaller copies each
# entry into the executable's resources without looking at it, and Inno Setup
# takes the file as it finds it.
#
# The container is assembled here rather than by an image library because it is
# a header and sixteen bytes per entry, and because doing it in the open is what
# makes the paragraph above checkable.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)

app_id=io.github.RonnyPfannschmidt.GTKPass
source=$repo/data/icons/hicolor/scalable/apps/$app_id.svg
target=$repo/data/icons/$app_id.ico

command -v rsvg-convert >/dev/null || {
    echo "rsvg-convert is needed to render the icon and was not found" >&2
    exit 1
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

sizes=(16 24 32 48 64 128 256)
for size in "${sizes[@]}"; do
    rsvg-convert --width "$size" --height "$size" \
        --output "$work/$size.png" "$source"
done

SIZES="${sizes[*]}" WORK="$work" TARGET="$target" python3 - <<'PY'
"""Assemble the rendered PNGs into an .ico. Standard library only."""

import os
import struct
from pathlib import Path

work = Path(os.environ["WORK"])
sizes = [int(size) for size in os.environ["SIZES"].split()]

images = [(size, (work / f"{size}.png").read_bytes()) for size in sizes]

# ICONDIR: reserved, type (1 = icon), image count.
header = struct.pack("<HHH", 0, 1, len(images))
# Each ICONDIRENTRY is 16 bytes, and the payloads follow all of them.
offset = len(header) + 16 * len(images)

entries = bytearray()
for size, data in images:
    entries += struct.pack(
        "<BBBBHHII",
        # 256 does not fit in a byte and is written as 0; the format has said so
        # since the 256 pixel sizes were introduced, and every reader knows it.
        size if size < 256 else 0,  # width
        size if size < 256 else 0,  # height
        0,  # palette size, 0 meaning no palette
        0,  # reserved
        1,  # colour planes
        32,  # bits per pixel
        len(data),
        offset,
    )
    offset += len(data)

Path(os.environ["TARGET"]).write_bytes(
    header + bytes(entries) + b"".join(data for _, data in images)
)
PY

printf 'wrote %s (%s bytes, sizes: %s)\n' \
    "$target" "$(stat -c%s "$target")" "${sizes[*]}"
