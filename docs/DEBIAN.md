# Packaging GTKPass for Debian and Ubuntu

A `.deb` from the same sdist the RPM is built from, installing the same files
in the same places. Fedora's side of this is [PACKAGING.md](PACKAGING.md), which
also covers the systemd-sysext image; the Flatpak is [FLATPAK.md](FLATPAK.md)
and Windows is [WINDOWS.md](WINDOWS.md).

```bash
make deb                            # dist/deb/gtkpass_*_all.deb, for Debian trixie
DEB_TARGET=ubuntu:26.04 make deb    # ... or for the current Ubuntu LTS
```

Nothing is released anywhere. This is `make deb` on a checkout, not a
distribution channel: no repository, no signature, and no upload to Debian.

## Which targets, and why not the others

**Debian trixie** and **Ubuntu 26.04 LTS**, which is the same shape as the
Fedora matrix — the floor and the current release. Trixie has GTK 4.18 and
libadwaita 1.7; Ubuntu 26.04 has 4.22 and 1.9, so a break between them is a
version difference in the stack, which is what a single target would hide.

Two releases people will ask about are deliberately absent.

**Debian bookworm** carries GTK 4.8. The application requires 4.10, and
`debian/control` says so, so the package would refuse to install rather than
misbehave — but it would refuse for everyone on bookworm, which is why the
floor is trixie.

**Ubuntu 24.04 LTS** fails for a reason that has nothing to do with GTK: its
`python3-setuptools` is 68.1.2, and `pyproject.toml` declares its licence in the
PEP 639 form that needs setuptools 77 or newer — which it also asks for in
`build-system.requires`. The wheel build itself stops there:

```
configuration error: `project.license` must be valid exactly by one definition
```

No arrangement of the packaging gets around that. What would is either fetching
a newer setuptools from PyPI into a distribution build — which is precisely the
thing a distribution package exists not to do — or writing the licence metadata
in the older form, which is a change to the project rather than to its
packaging. So 24.04 is out until it is out of support.

## Why the build runs in a container

Same reason as the RPM's: this is developed on an ostree Fedora, which has no
`dpkg` at all, and the container pins *which* release the package is built for.
That is not a detail here either — the wheel installs under
`/usr/lib/python3/dist-packages`, and what builds it is the target's own
setuptools, which is exactly what rules 24.04 out above.

`packaging/Containerfile.build.deb` prepares the image, one file for both
targets with `BASE_IMAGE` naming which, and `deb_builder_image` in
`packaging/builder-image.sh` builds it on demand. The layers are ordered so a
source change reuses the toolchain, and the tag carries the base image so the
two targets cannot share a cached image and quietly build for each other.

CI does not use the image: those jobs run *inside* the target already, so they
take the `USE_CONTAINER=0` path — the same arrangement, and the same script
(`packaging/debuild-here.sh`), as the RPM's.

## Nothing is written down twice

That is most of what there is to say about `debian/control`.

- **The Python dependencies are not in it.** `dh_python3` reads the wheel's own
  metadata and emits `${python3:Depends}`, which resolves to `python3-gi`,
  `python3-gnupg` and `python3-secretstorage` with no mapping table to keep in
  step. Adding a dependency to `pyproject.toml` is the whole of adding it.
- **What is in it is what no Python metadata can express**: GTK and libadwaita,
  as `gir1.2-gtk-4.0` and `gir1.2-adw-1`, with the minimum versions
  `packaging/gtkpass.spec` requires of `gtk4` and `libadwaita`. Those are the
  same fact in two packages' spellings, so `tests/test_deb_packaging.py` fails
  if one is raised without the other.
- **The build dependencies are read back out of it.**
  `packaging/deb-builddeps.sh` prints them, and both the container image and
  `debuild-here.sh` install from that one list — the Debian counterpart of
  `buildreqs-from-pyproject.py`.

## Versions

`packaging/deb-version.sh` derives the version from git, in the three states a
checkout can be in, and prints two words: the upstream version — what the sdist
and the wheel inside it are built as — and the Debian version.

```
0.2.1 0.2.1+git20260812.72ddf59-1
```

The ordering is the point, and dpkg's spelling of it is not rpm's:

| state | version | sorts |
| --- | --- | --- |
| before any tag | `0.1.0~git<date>.<hash>-1` | *before* `0.1.0-1`, so the release upgrades over it |
| on a tag | `0.2.1-1` | is that release |
| on a tag, dirty | `0.2.1+git<date>.<hash>.dirty-1` | *after* it: that release plus uncommitted changes |
| after a tag | `0.2.1+git<date>.<hash>-1` | after that release, before the next |

`~` sorts before nothing at all and `+` sorts after, which is what makes the
first and last rows different. Getting them the wrong way round produces a
package that installs, runs, and then declines to be upgraded by the actual
release — and nothing notices until the release. `tests/test_deb_packaging.py`
builds each of these in a throwaway repository and asks `dpkg
--compare-versions`, so the table above is checked rather than believed.

The date is the commit's, not today's, so building the same commit twice gives
the same package.

## What the package installs

Everything under `/usr`, as the RPM does:

- `/usr/bin/gtkpass`, with no wrapper around it
- the wheel into `/usr/lib/python3/dist-packages/gtkpass/`, `.ui` files,
  `demo.json` and `entry_points.txt` included — without which the application
  fails on import, or loads with no backends
- the desktop entry, AppStream metainfo and icon, named after the application id
- the GSettings schema as **uncompiled** `.xml`

`dist-packages` is the one visible difference between this package and the RPM,
and it cost one line: `packaging/smoke-test-install.sh` checks that what
imported is the installed copy and not a checkout, and it did that by looking
for `site-packages` — which is every layout except Debian's. It accepts both now.

The schema ships uncompiled for the same reason as on Fedora: `libglib2.0`
carries a dpkg trigger that recompiles
`/usr/share/glib-2.0/schemas/gschemas.compiled` when a package adds one, and
that file holds every application's schemas, so shipping a copy would overwrite
the lot.

`debian/rules` validates the desktop entry, the metainfo and the schema at build
time — the spec's `%check`, on the same three files. The suite is not run there:
it needs a display, a private session bus and a GPG key, which is what `make
test` against the installed package is for.

## What CI does with all this

`.github/workflows/ci.yml` builds the `.deb` on both targets, installs it with
`apt-get install ./…deb` — apt rather than `dpkg -i`, so the dependency metadata
is resolved rather than assumed — and then runs `make test PYTHON=python3` and
`packaging/smoke-test-install.sh` against the installed copy. That is the same
pair of steps the RPM job runs, through the same Makefile target.

One package in those jobs is worth knowing about: **`xauth`**. Fedora's Xvfb
package pulls it in and Debian's does not, so without it `xvfb-run` stops with
`xauth command not found` before a single test has run.

## What has and has not been verified

Built and checked, on both targets, in the shape CI uses: the package builds
from the sdist, installs with its dependencies resolved by apt, and the full
suite passes against the installed copy — 845 tests, plus the smoke test finding
the launcher on `PATH`, the schema in the system cache, all four backends
discoverable and the packaged `.ui` files loading.

Not done:

- Not signed, and there is no repository to install from.
- Not uploaded to Debian or to a PPA, and not reviewed by either. `Standards-
  Version` and the `debian/copyright` file are written as though it might be,
  but nothing has checked that claim — `lintian` is not run anywhere yet.
- `Architecture: all`, and only built and tested on amd64.
- No `debian/watch`, there being no upstream tarball release to watch.
