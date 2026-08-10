# Working on GTKPass

GTKPass is a GTK4/Libadwaita frontend over pluggable password backends, not a
password manager of its own. Backends are discovered through the
`gtkpass.backends` entry point group.

## Never read real passwords

The single rule that matters most. Development code, tests, probes and one-off
scripts must never open `~/.password-store` or the user's keyring. Whatever they
print lands in a terminal, a CI log, or an AI assistant's transcript, and a
decrypted password cannot be un-disclosed.

- The backends refuse the real store, and the keyring, **whenever the code is
  running out of a checkout** — which is everything you will ever run here.
  `safety.running_from_checkout()` asks the installed distribution: an editable
  install records `dir_info.editable` in its `direct_url.json`, and that is the
  only signal that *means* editable rather than resembling it. The metadata is
  believed only when it describes the module actually running, so a checkout
  ahead of an installed release on `sys.path` is still a checkout.
  An installed build is allowed, because refusing there would only mean every
  package shipping a wrapper to undo it.
- **GTKPass has to be installed to run at all.** `safety.require_installed()`
  runs on import of `gtkpass` and refuses a bare `PYTHONPATH=src` process,
  which has no metadata and so settles nothing about what is executing. A
  leftover `src/gtkpass.egg-info` does not count as an install either: it is a
  build artefact inside a source tree, it carries no `direct_url.json`, and
  before it was excluded it made a `PYTHONPATH` run look like a packaged one
  and opened the guard. Use `make sync`.
- `GTKPASS_ALLOW_REAL_STORE` overrides that in both directions. `run_app.sh`
  sets it to 1, launching a checkout being the one case where the checkout
  really is the application. If you are reaching for that variable anywhere
  else, stop.
- `make devstore` creates a throwaway store under `.dev/` with invented
  passwords and its own GPG key. Use it for manual testing and screenshots. It
  drops a `.gtkpass-scratch-store` marker, which is what lets the guard open
  that store while still refusing everything else.
- `make run-dev` launches against it **with the guard still armed**. It passes
  `GTKPASS_ALLOW_REAL_STORE=0` on purpose: it goes through `run_app.sh`, which
  opts in, and without turning that back off the development run would be the
  one thing running unguarded.
- The test suite clears the variable in `conftest.py`, so an exported value in
  your shell cannot re-enable it for a run.

The keyring is covered too, not just the file stores.
`SecretServiceBackend.is_available()` opens the user's default collection and
can prompt them to unlock it, so without the opt-in it reports unavailable
instead of probing, and `create()` refuses outright.

Never print a decrypted value. `PasswordEntry.__repr__` is redacted on purpose:
the generated dataclass repr would have put plaintext into every log line,
traceback and pytest assertion diff that rendered one. Do not undo that, and do
not add a `__str__` or a log line that defeats it.

## Test first

Write the failing test, run it, watch it fail, then make it pass. Not "when
appropriate" — the previous wording said that and it never once happened, which
is why a syntax error and a backend that could not be instantiated both survived
seven months in the tree.

The backend conformance suite in `tests/test_backend_contract.py` is the
definition of done for backend work.

## UI lives in Blueprint

Widgets are declared in `src/gtkpass/ui/blueprints/*.blp` and loaded as
templates. Edit the `.blp`, run `make ui`, commit both files, and never hand-edit
a `.ui` — it is generated. A test parses every module and fails on widget
construction in Python; models such as `Gio.ListStore` are exempt.

That includes list and column view rows, which are declared as a
`BuilderListItemFactory` template rather than built in a factory callback — see
`password_list.blp`. Those bindings only run when a row is built, so a broken
one leaves the model correct and the view empty; at least one test has to
present the widget and read back what it rendered.

## Other things worth knowing

- Import GI namespaces from `gtkpass._gi`, which pins the versions once. Never
  call `gi.require_version` anywhere else.
- Nothing outside `backends/manager.py` imports a backend module directly.
- The window loads its backends asynchronously, so a test that wants one has to
  turn the main loop until it arrives -- `loaded_window` and `listed_window` in
  `tests/test_window.py` are the two places that wait. Nothing slow may be added
  to `GTKPassWindow.__init__`: a constructor that runs git or talks to D-Bus is
  a window that does not appear.
- What the manager hands out is a `SerializedBackend`, not the backend itself.
  A method added to the backend contract has to be forwarded there too, or it
  will answer for the proxy instead of for the backend; the contract suite
  checks that.
- Backends must never re-encrypt a store to a changed recipient set. Reporting
  the change is `backends/recipients.py`; acting on it is `pass init`, and doing
  it automatically would carry out the attack it exists to detect.
- Application identity lives in `gtkpass/config.py`. The D-Bus name, desktop
  file, icon, AppStream id and GSettings schema all have to stay the same string.
- `Gio.Settings.new()` on a missing schema calls `g_error()` and aborts the
  process without a traceback, so go through `config.get_settings()`.
- Do not add dependencies without discussion. In particular not `keyring`,
  `GitPython`, `qrcode`, `pillow` or `opencv`: an earlier version of this file
  prescribed all of them and none were ever used. `pyotp` is the one that has
  since become arguable, OTP being planned — argue it rather than assume it,
  because RFC 6238 over `hmac` and `hashlib` is a short function with no
  dependency at all.
- An installed build must work with nothing set in its environment. There is no
  launcher script in any package, so anything the application needs arranged, it
  arranges itself — see `safety.running_from_checkout()`,
  `config.schema_source()` and `frozen.configure_environment()`, which is the
  same rule reaching Windows: a PyInstaller bundle carries its own GTK and its
  own compiled schema, on paths GLib has no reason to look at.
- Not everything is Linux. The Windows build is a frozen bundle over a pinned
  gvsbuild GTK stack (`packaging/windows/`, `docs/WINDOWS.md`), and anything
  platform-specific added to a backend or to `pyproject.toml` needs a marker or
  a guard rather than an assumption. `secretstorage` is the worked example.

## Commands

`make help` lists them. `make check` runs lint, format and types via pre-commit;
`make test` runs the suite headless under xvfb, on its own X server and its own
D-Bus session. Both halves are deliberate: GDK ignores `DISPLAY` whenever
`WAYLAND_DISPLAY` is set, and a desktop session exports `GDK_BACKEND=wayland`
itself, so xvfb alone put every window on the real screen and let a clipboard
test overwrite whatever the developer had copied. conftest sets the same thing
again for a bare `pytest`.

CI packages first and tests the packages: it builds the wheel, sdist and RPMs,
then runs this suite against each of them installed, over two Fedora releases.
It also freezes the Windows bundle out of that same wheel and checks it, built
and again installed; that job is non-blocking on purpose, and `docs/WINDOWS.md`
says why.
`make test` here runs against the editable install instead, which is faster and
what you want while working -- but it is not what CI checks, so a failure that
only appears once something is packaged will appear there and not here.

`make sync` installs the pre-commit hook (`make hooks` on its own if the
environment already exists), and that hook is what catches an unformatted commit
before it is made rather than after.

`uv run` outside the Makefile re-resolves the environment and tries to build
PyGObject and pycairo, which fails. Set `UV_NO_SYNC=1`, as the Makefile does.
