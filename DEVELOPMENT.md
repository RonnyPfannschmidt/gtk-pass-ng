# GTKPass Development Setup

Read [AGENTS.md](AGENTS.md) first. It is short, and its first rule — never let
development code read your real password store — is the one that cannot be
undone if you get it wrong.

## System dependencies

PyGObject and pycairo are taken from your distribution rather than built from
PyPI: they need cairo, girepository and GTK development headers to compile, and
the distribution's builds are already linked against the GTK the application
will actually run on.

**Fedora**

```bash
sudo dnf install python3 gtk4 libadwaita python3-gobject \
    gobject-introspection glib2-devel gnupg2 xorg-x11-server-Xvfb
```

**Ubuntu/Debian**

```bash
sudo apt install python3 libgtk-4-1 libadwaita-1-0 python3-gi \
    gir1.2-gtk-4.0 gir1.2-adw-1 libglib2.0-dev-bin gnupg xvfb
```

**Arch**

```bash
sudo pacman -S python gtk4 libadwaita python-gobject \
    gobject-introspection glib2 gnupg xorg-server-xvfb
```

[uv](https://docs.astral.sh/uv/) manages the Python side.

## Setting up

```bash
git clone https://github.com/RonnyPfannschmidt/gtk-pass-ng.git
cd gtkpass
make sync
```

`make sync` creates the virtual environment against the *system* interpreter
with `--system-site-packages` — a uv-managed Python's site-packages does not
contain the distribution's GTK bindings — installs the dependencies with
PyGObject and pycairo excluded, and installs the pre-commit hook.

If you find yourself running `uv run` by hand, set `UV_NO_SYNC=1`. Without it
uv re-resolves the environment and tries to build the excluded packages again.
The Makefile exports it for you.

## Everyday commands

`make help` lists them all.

| Command | What it does |
| --- | --- |
| `make run` | launch the application against your real store |
| `make run-dev` | launch against a throwaway store of invented entries |
| `make devstore` | create that throwaway store under `.dev/` |
| `make test` | the test suite, headless under xvfb |
| `make check` | every pre-commit hook: lint, format, types |
| `make ui` | compile `.blp` sources to `.ui` |
| `make schemas` | compile the GSettings schema |
| `make hooks` | install the pre-commit hook into `.git` |
| `make rpm` | build the RPM in a Fedora container |
| `make sysext` | build a systemd-sysext image for the ostree desktops |

## Never test against your own passwords

`make devstore` builds a store under `.dev/` with invented passwords and its
own GPG key, and `make run-dev` launches against it. Use those for manual
testing and screenshots.

The backends refuse `~/.password-store`, `$PASSWORD_STORE_DIR` and the session
keyring whenever the code is running out of a checkout — which is everything you
run here, the editable install `make sync` creates included. An installed build
is allowed, being the application actually in use.

A bare `PYTHONPATH=src` run is refused outright, at import: with no distribution
metadata there is nothing to establish what is running, and guessing is what the
guard exists to avoid. `make sync` is the answer to that error.
`GTKPASS_ALLOW_REAL_STORE` overrides the decision either way; `run_app.sh` sets
it to 1, and `conftest.py` clears it so an exported value in your shell cannot
re-enable it for a test run.

The development store is exempt on its own merits rather than by disabling the
guard: `make devstore` writes a `.gtkpass-scratch-store` marker into it, and a
marked directory is not treated as a real store even when `PASSWORD_STORE_DIR`
points at it. That is why `make run-dev` passes `GTKPASS_ALLOW_REAL_STORE=0` —
it launches through `run_app.sh` and has to turn the default back off, or the
one command meant to be safe would be the one running unguarded. Delete the
marker and the directory becomes a real store again.

`~/.password-store` can never be marked scratch; a stray marker there would
otherwise disarm the guard completely.

Never print a decrypted value, and do not defeat the redacted
`PasswordEntry.__repr__`.

## Tests

```bash
make test                       # everything, headless
UV_NO_SYNC=1 uv run pytest tests/test_backend_contract.py
UV_NO_SYNC=1 uv run pytest -m "not gui"      # no display needed
```

Anything touching widgets needs a display, so `make test` wraps the run in
`scripts/headless-session.sh`: an Xvfb display with GDK actually pointed at it,
a private D-Bus session — which keeps the tests away from your real keyring —
and a private `XDG_RUNTIME_DIR`.

### Why the tests get their own runtime directory

The third one looks like belt and braces and is not. `xdg-document-portal`
mounts itself at `$XDG_RUNTIME_DIR/doc`, and `dbus-run-session` inherits
`XDG_RUNTIME_DIR` from the session around it. So anything on the test bus that
activated `org.freedesktop.portal.Documents` got a *second* portal aimed at the
same `/run/user/$UID/doc` as your real one. That mount is `auto_unmount`: when
the test bus exited, it was torn down — and the real session's mount went with
it. After a test run, every flatpak on the machine died at launch with

```
bwrap: Can't find source path /run/user/1000/doc/by-app/<app-id>
```

`systemctl --user status xdg-document-portal` reported `active (running)` with
no restarts and an empty journal throughout, because the service was never the
process that died. `findmnt /run/user/$UID/doc` is the check that answers it.

Two things about the fix, both of which look like details and are not:

- It is a *private* directory, not an unset variable. With `XDG_RUNTIME_DIR`
  unset, `g_get_user_runtime_dir()` falls back to the user cache directory and
  the portal mounts at `~/.cache/doc` instead — a documented upstream nuisance
  ([xdg-desktop-portal#512](https://github.com/flatpak/xdg-desktop-portal/issues/512)),
  not an improvement.
- It has to be set *outside* `dbus-run-session`. Setting it in `conftest.py`
  does nothing: dbus-daemon is already running by then, and it starts activated
  services with its own environment rather than pytest's.

It cuts one more thread while it is there, which is worth knowing about: a
gnome-keyring client finds the daemon through
`$XDG_RUNTIME_DIR/keyring/control`, so a private runtime directory means the
tests cannot reach the real keyring by that route either, private bus or not.

`tests/test_headless_isolation.py` asserts that every headless invocation — the
Makefile, `packaging/test-sysext.sh`, the CI workflow — goes through the
wrapper. CI has no real portal to protect, so that wiring check is the only
thing that can notice the isolation being dropped.

Registered markers:

| Marker | Meaning |
| --- | --- |
| `gui` | needs a display |
| `requires_gpg` | needs a working `gpg` |
| `requires_pass` | needs the `pass` CLI |
| `slow` | slow running |

Write the failing test first, run it, watch it fail, then make it pass. The
backend conformance suite in `tests/test_backend_contract.py` is the definition
of done for backend work.

## Changing the interface

Widgets are declared in `src/gtkpass/ui/blueprints/*.blp` and loaded as
templates. Edit the `.blp`, run `make ui`, and commit both files. Never
hand-edit a `.ui`: it is generated.

A test parses every module and fails on widget construction in Python, so a
widget tree has to stay in Blueprint. Models such as `Gio.ListStore` are
exempt; see `NON_WIDGET_TYPES` in `tests/test_ui_is_declarative.py`.

Rows for a list or column view are declared too, as a `BuilderListItemFactory`
template — see `password_list.blp`. Because those bindings are only exercised
when a row is built, at least one test presents the widget and reads back what
it rendered.

## Dev container

`.devcontainer/` sets up dependencies on start and supports Wayland and X11.
`.devcontainer/check_display.sh` reports which backend is available. For X11
from the host, `xhost +local:` first. See
[docs/DEVCONTAINER_GUI.md](docs/DEVCONTAINER_GUI.md).

## Troubleshooting

**`Gio.Settings` aborts with no traceback.** `Gio.Settings.new()` calls
`g_error()` on a missing schema, which kills the process outright. Go through
`config.get_settings()`, and run `make schemas`.

**A schema change has no effect.** GLib reads `gschemas.compiled` and ignores
the `.xml` beside it, so a stale compiled blob wins. Re-run `make schemas`.

**`uv sync` tries to build pycairo and fails.** The environment was created
against a uv-managed Python instead of the system one. Remove `.venv` and run
`make sync`.

**Tests emit D-Bus and portal warnings.** Expected under
`scripts/headless-session.sh`; there is no secret service on the private bus.

**Flatpaks stop launching after a test run.** `bwrap: Can't find source path
/run/user/$UID/doc/...` means the document portal's mount is gone. Check with
`findmnt /run/user/$UID/doc`, not `systemctl status`, which reports healthy
either way. If it happens, something ran a bus without the private runtime
directory; see above. `systemctl --user restart xdg-document-portal` puts the
mount back.
