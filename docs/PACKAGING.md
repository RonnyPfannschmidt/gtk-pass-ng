# Packaging GTKPass for Fedora

Two artefacts from the same spec: an RPM for a package-based Fedora, and a
systemd-sysext image for the ostree desktops — Bluefin, Silverblue, Bazzite —
where installing a package means rebuilding the deployment and rebooting.

The Flatpak is a third route with a different story; it lives in
[FLATPAK.md](FLATPAK.md).

```bash
make rpm      # dist/rpm/gtkpass-*.noarch.rpm and the matching .src.rpm
make sysext   # dist/sysext/gtkpass-<id>-<version>.raw
```

Neither is released anywhere. Both are built locally, from a working tree.

## Why the build runs in a container

`rpmbuild` runs inside `registry.fedoraproject.org/fedora:$VERSION_ID` rather
than on the machine doing the work. This is developed on Bluefin, where layering
`rpm-build` in order to package something costs a reboot and leaves a permanent
addition to the image.

The container also pins *which* Fedora the package targets, and that is not a
detail. The wheel installs into `/usr/lib/python3.14/site-packages`, a path that
names the interpreter; a package built against Fedora 43's python3.13 installs
nothing importable on a python3.14 host. `FEDORA_RELEASE=43 make rpm` builds for
another release, and the default follows `VERSION_ID` from `/etc/os-release` —
which on the derivatives reports Fedora's release even though `ID` reports their
own name.

## Versions

There are no tags, so there is no upstream release to build from.
`build-rpm.sh` pins the sdist to `0.1.0` via `SETUPTOOLS_SCM_PRETEND_VERSION`
and puts the commit into `Release` in Fedora's pre-release form:

```
gtkpass-0.1.0-0.1.20260808git49c7b8d.fc44.noarch.rpm
```

`0.1.0-0.1.<snapshot>` sorts *before* an eventual `0.1.0-1`, so a real release
will upgrade over any snapshot ever installed. The date is the commit's, not
today's, so building the same commit twice gives the same package; a dirty tree
appends `.dirty`, because such a build does not describe the commit it names.

## What the RPM installs

Everything under `/usr`:

- `/usr/bin/gtkpass` — the console script, with no wrapper around it
- the wheel into `/usr/lib/python3.N/site-packages/gtkpass/`, including the
  compiled `.ui` files and `demo.json`, which are loaded through
  `importlib.resources` and without which the application fails on import
- the desktop entry, AppStream metainfo and icon, all named after the
  application id
- the GSettings schema as **uncompiled** `.xml`

There is no launcher script, and that is worth one line because it constrains
the application rather than the package: an installed build has to work with
nothing set in its environment. Two things follow from it. `safety.py` refuses
the user's own store only when it is running out of a checkout, so a packaged
build opens it as any password manager would. And `config.py` finds its schema
without `GSETTINGS_SCHEMA_DIR` being set for it, which is what the next section
is about.

The schema ships uncompiled on purpose. `glib2` carries a file trigger that
recompiles `/usr/share/glib-2.0/schemas/gschemas.compiled` whenever a package
adds or removes a schema, so the RPM does not have to — and must not, because
that file holds every application's schemas and shipping one would overwrite the
lot.

`%check` validates the desktop entry, the AppStream metainfo, and the schema
with `glib-compile-schemas --strict --dry-run`. That last one earns its line:
`Gio.Settings` calls `g_error()` on a schema it cannot parse, which kills the
process at startup with no traceback. The test suite is not run there — it needs
a display, a private D-Bus session and a GPG key, which is what `make test` is.

## The sysext image

`systemd-sysext` overlays a squashfs of `/usr` content onto the running system.
It modifies no deployment and survives no upgrade of one:

```bash
sudo cp dist/sysext/gtkpass-bluefin-44.raw /var/lib/extensions/
sudo systemd-sysext merge      # and `unmerge` to take it away again
```

`systemd-sysext.service` re-merges at boot.

### One image per target

An extension names the operating system it was built for, in
`/usr/lib/extension-release.d/extension-release.gtkpass`, and systemd refuses to
merge it anywhere else:

```
ID=bluefin
VERSION_ID=44
SYSEXT_SCOPE=system
SYSEXT_LEVEL=1.0
```

By default that is the machine doing the building. Name another target
explicitly to build for it:

```bash
SYSEXT_ID=fedora SYSEXT_VERSION_ID=44 make sysext
```

The RPM inside is built for the same target — that is where the interpreter
version in those paths gets decided — and the build refuses to package an RPM
from `dist/rpm` that was built for a different release.

systemd would also accept `ID=_any`, which skips the check entirely and lets one
image merge onto anything. This deliberately does not offer it. The check is the
whole safety of the arrangement: the image carries a wheel under
`/usr/lib/python3.N/site-packages`, so merged onto a host with a different Python
it lands where nothing imports from and the application is simply missing — and
that is the *better* of the two ways it can go wrong. An image that merges
anywhere is an image that was tested nowhere.

### What travels inside it

`build-sysext.sh` starts from the RPM and asks the running system which of its
requirements are unsatisfied, rather than working from a fixed list — the answer
depends on what the user has layered. On a stock Bluefin it is `python3-gnupg`
and nothing else: GTK4, libadwaita, PyGObject, secretstorage, gnupg2, `pass` and
git are all in the base image. Shipping second copies of those would be both
large and a way to run a different GTK than the desktop is.

Whatever is missing is downloaded and unpacked into the image, and its own
requirements are checked the same way, so a vendored package that needs
something the host has not got pulls that in too.

### Two things an extension must not do

Both are the same mistake, and both break the desktop rather than the
application.

**The schema cache.** `/usr/share/glib-2.0/schemas/gschemas.compiled` is a single
file holding every installed application's schemas. An overlay is not a merge at
file level: an extension shipping its own copy *hides* the host's, and the
session comes up with GNOME's own settings missing. So the build compiles the
schema into `/usr/share/gtkpass/schemas/` instead, and `config.schema_source()`
adds that directory to GLib's schema search path when it exists — in addition to
the default locations, not instead of them, so the plain RPM and a checkout are
both unaffected. An unreadable directory there is logged and ignored rather than
allowed to take the application down at startup.

**Every other merged cache.** `icon-theme.cache`, `mimeinfo.cache` and their kind
are the same shape of file, and the build deletes any that arrive.

A consequence worth knowing: because the host's icon cache is left alone and does
not mention the application, GTK has to fall back to scanning the icon directory
to find it. If the icon does not appear in the shell, that is why.

`ARCHITECTURE` is deliberately absent from the extension-release — systemd only
checks it when set, and everything in the image is noarch.

## What has and has not been verified

Built, and checked: the RPM builds clean in a Fedora 44 container, its contents
are what the spec claims, and the only requirement the host cannot satisfy is
`python3-gnupg`. The staged sysext tree has been exercised end to end with no
GTKPass environment variables set at all — modules imported from it, the guard
reporting the tree as an installed build rather than a checkout, the schema
resolved from the private directory, and six entries listed and one decrypted
from a scratch store.

Not done:

- Neither artefact is signed, and there is no repository to install from. This is
  `make rpm` on a checkout, not a distribution channel.
- No COPR build, and no Fedora review request.
- The image has been built but not merged with `systemd-sysext merge` on a live
  session, and the RPM has not been installed on a package-based Fedora.
