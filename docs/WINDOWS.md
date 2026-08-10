# GTKPass on Windows

A release attaches two Windows artefacts, both 64-bit:

| File | What it is |
| --- | --- |
| `gtkpass-<version>-windows-x64.zip` | Unpack it anywhere and run `gtkpass\gtkpass.exe`. Nothing is written outside the folder except the settings. |
| `gtkpass-<version>-windows-x64-setup.exe` | Installs per-user, no administrator, with a Start Menu entry and an uninstaller. Choose a machine-wide install in the wizard if you want one. |

Neither is signed. Windows SmartScreen will say so on first run, and there is
nothing in this repository that can make it stop saying so — a certificate costs
money and has to belong to somebody.

## What works there, and what does not

This is a frontend over pluggable backends, and the backends are where the
platform shows through.

| Backend | On Windows |
| --- | --- |
| Demo | Works. It is invented data with no store behind it. |
| Direct GPG | Works with [Gpg4win](https://gpg4win.org/) installed; the backend looks for `gpg` on `PATH`. |
| Pass | Needs the `pass` shell script, which is a Bash program. It reports itself unavailable unless you have arranged one, under WSL or otherwise. |
| Secret Service | Linux only. It is a D-Bus interface, and there is no D-Bus session bus to reach; it reports itself unavailable. |

`secretstorage` is therefore a Linux-only dependency in `pyproject.toml`. It was
unconditional until the Windows build existed, which made the whole distribution
uninstallable there for the sake of a backend that cannot work anyway.

Sync over ssh works if `git` is on `PATH`. The Flatpak permission machinery in
`gtkpass/sandbox.py` has nothing to do on Windows and answers that everything is
permitted, which on a machine with no sandbox is true.

## Building it

```powershell
pwsh -File packaging\windows\build.ps1
```

Roughly ten minutes on a cold machine, most of it the download. Everything
lands in `build\windows` (working files, reused between runs) and
`dist\windows` (the artefacts). `-SkipInstaller` stops after the zip, for a
machine without Inno Setup.

Then, to check what came out:

```powershell
pwsh -File packaging\windows\smoke-test.ps1
```

That runs the bundle's own `--self-check`, which is where the checks
`packaging/smoke-test-install.sh` makes from outside an RPM had to move to:
there is no interpreter beside a frozen bundle to run them from. It is also the
part of this that can be exercised on Linux, and was — PyInstaller and the spec
work the same there, so the spec, the launcher and `gtkpass/frozen.py` can be
built and run without a Windows machine. What cannot is everything from
gvsbuild and Inno Setup onwards.

### Where GTK comes from

PyGObject is published to PyPI as a source distribution and nothing else, so
`pip install pygobject` on Windows needs a C compiler and the headers of the
entire GTK stack. There is no wheel to fall back on.

[gvsbuild](https://github.com/wingtk/gvsbuild) is the GTK project's own MSVC
build of that stack, and its GTK4 release archive settles the problem outright:
it carries GTK4, libadwaita, the Adwaita icon theme and the introspection
typelibs, and — the part that decides everything else — PyGObject and pycairo
already built, as wheels.

Those wheels are built for **one** Python version. A `cp314` wheel does not
install on 3.13, and the interpreter running the build is the one the bundle
carries, so `build.ps1` checks the version and stops rather than failing later
with something less clear. Two pins therefore move together: `GvsbuildVersion`
and `ExpectedPythonVersion` in `build.ps1`, and the `python-version` in the
Windows CI job.

The release is pinned rather than tracked. An unpinned "latest" would change
the GTK version, and the Python version required alongside it, under a build
that worked yesterday.

Getting `import gi` to work against that stack takes two things that are not
obvious and that fail in ways pointing somewhere else:

- **`os.add_dll_directory`, not `PATH`.** Python 3.8 stopped searching `PATH`
  for the DLLs an extension module depends on, and PyGObject does not call
  `add_dll_directory` itself — there is no Windows DLL handling in
  `gi/__init__.py` at all. `build.ps1` drops a `.pth` file into the build
  environment that does it, a `.pth` because PyInstaller asks what a typelib
  needs from isolated subprocesses of its own, which inherit the environment
  but nothing the parent did to itself. Without it: `DLL load failed while
  importing _gi`.
- **`GI_TYPELIB_PATH`.** Otherwise `gi.require_version('Gtk', '4.0')` fails
  during the build, PyInstaller's gi hook concludes the module is unavailable
  and collects *nothing*, and the build succeeds. The failure surfaces when the
  finished bundle is started, which is the last place anyone looks for it.

`build.ps1` imports Gtk and Adw itself, before PyInstaller runs, for exactly
that reason: a hook that quietly collects nothing is worth failing early over.

One more, of the same family: `pip install --force-reinstall <wheel>`
reinstalls the *dependencies* too, and PyGObject and pycairo are dependencies.
pip goes to PyPI, finds the source distributions, builds them, and replaces
what gvsbuild built. The application is therefore installed on its own, with
the dependency resolution run separately where those two are already satisfied.

### What the bundle has to carry

PyInstaller freezes the application; the rest of this is what a GTK application
needs that a Python one does not, and every piece of it is somewhere GLib would
not look by itself.

PyInstaller's own hooks handle most of it — `GI_TYPELIB_PATH`, the gdk-pixbuf
loader cache that renders every symbolic icon in the interface, and
`XDG_DATA_DIRS` for the icon theme. Two things they do not handle:

- **The GSettings schema.** PyInstaller collects GTK's schema *sources* from
  the gvsbuild prefix and compiles them itself, discarding any
  `gschemas.compiled` handed to it — so `build.ps1` stages this application's
  `.gschema.xml` rather than a compiled copy, and the two end up in one cache.
  That is what the file is: one cache per directory, not one per package.
  Staging a compiled file instead does not fail, it is simply dropped, and the
  application ships unable to find its own settings.

  Finding the cache is the other half, and PyInstaller does not do that part.
  `gtkpass/frozen.py` points `GSETTINGS_SCHEMA_DIR` at it on import, before
  anything reaches `gi.repository`, because GLib caches its schema source the
  first time it is asked.
- **The distribution metadata.** Backends are discovered through the
  `gtkpass.backends` entry point group, which is read out of the installed
  `.dist-info`. Without it the application starts with no backends and nothing
  in the log to say why. The spec collects it with `copy_metadata`, and names
  the backend modules as hidden imports besides — nothing *imports* them, the
  entry point names them as a string, so PyInstaller's import graph never sees
  them.

There is no launcher script in the bundle, and there is not one in the RPM or
the sysext image either. Whatever the application needs arranged, it arranges
itself. That constraint is the same one arriving from a different direction, and
it is why the schema handling lives in `gtkpass/frozen.py` rather than in a
`.bat` file beside the executable.

### The safety guard

`gtkpass/safety.py` refuses the user's own password store when the code is
running out of a checkout, and a frozen bundle is not one: it is built by a
release job out of an installed wheel. `running_from_checkout()` says so
directly when `sys.frozen` is set, rather than reasoning about metadata that
describes a build machine's directory layout and answers nothing about this one.

`build.ps1` will not freeze an install from the working tree for the same
reason. An in-tree or editable install records itself as one in
`direct_url.json`, and a bundle frozen out of that would ship refusing to open
its owner's store.

## In CI

The `windows` job in `.github/workflows/ci.yml` builds the bundle from the wheel
the `distribution` job produced — the same file the Linux jobs install and the
release publishes — then runs the smoke test twice: once against what was built,
and once against what the installer put on disk, which is a different question. A
file left out of the installer's `[Files]` section is invisible until something
runs from the install directory.

The job is **non-blocking** (`continue-on-error: true`), and that is a decision
rather than an accident. Everything it depends on comes from off this
repository: a gvsbuild release archive, and an Inno Setup that happens to be
installed on GitHub's runner image. None of it is under the control of whoever
is trying to cut a release, and a mirror having a bad afternoon should not hold
one up. The release job attaches the Windows artefacts when they exist and says
nothing when they do not; the failed job says it itself, in the run.

Take that line out once the job has been boring for a while.

## The icon

Windows takes icons from an executable's resources and from the entries an
installer writes, and both want a `.ico`. There is no vector option anywhere in
that path — an icon resource holds raster images and nothing else, whatever the
source artwork was. So `data/icons/io.github.RonnyPfannschmidt.GTKPass.ico` is
committed next to the SVG, rendered from it at seven sizes by
`packaging/windows/make-icon.sh`. Run that when the SVG changes.

Two things about that file are deliberate:

- **Every size is rendered from the vector**, not scaled down from one large
  raster. Windows picks a size by context — 16 in a title bar, 32 in the
  taskbar, 256 in the large icon view — and a downscaled 256 loses the strokes
  in a symbolic-style icon at exactly the sizes that are seen most.
- **The images go in PNG-compressed**, which is what keeps it at 17 KB rather
  than 370. An `.ico` entry may hold either a raw bitmap or a whole PNG file,
  and a 256×256 raw entry alone is 270 KB of uncompressed BGRA. ImageMagick
  writes raw by default, which is what the first version of this did. Windows
  has read PNG entries since Vista, PyInstaller copies each entry into the
  executable's resources without looking at it, and Inno Setup takes the file
  as it finds it.

The script assembles the container itself, with the standard library, because
it is a header and sixteen bytes per entry — and because writing it in the open
is what makes the paragraph above checkable. It needs only `rsvg-convert`.
