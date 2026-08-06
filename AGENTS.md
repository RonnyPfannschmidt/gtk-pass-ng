# Working on GTKPass

GTKPass is a GTK4/Libadwaita frontend over pluggable password backends, not a
password manager of its own. Backends are discovered through the
`gtkpass.backends` entry point group.

## Never read real passwords

The single rule that matters most. Development code, tests, probes and one-off
scripts must never open `~/.password-store` or the user's keyring. Whatever they
print lands in a terminal, a CI log, or an AI assistant's transcript, and a
decrypted password cannot be un-disclosed.

- `make devstore` creates a throwaway store under `.dev/` with invented
  passwords and its own GPG key. Use it for manual testing and screenshots. It
  drops a `.gtkpass-scratch-store` marker, which is what lets the guard open
  that store while still refusing everything else.
- `make run-dev` launches against it **with the guard still armed**. It passes
  `GTKPASS_ALLOW_REAL_STORE=0` on purpose: it goes through `run_app.sh`, which
  opts in by default, and without turning that back off the development run
  would be the one thing running unguarded.
- The backends refuse the real store, and the keyring, unless
  `GTKPASS_ALLOW_REAL_STORE=1`. `run_app.sh` defaults it to 1 because that is
  the application actually being used. If you are reaching for that variable in
  anything else, stop.
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
- Application identity lives in `gtkpass/config.py`. The D-Bus name, desktop
  file, icon, AppStream id and GSettings schema all have to stay the same string.
- `Gio.Settings.new()` on a missing schema calls `g_error()` and aborts the
  process without a traceback, so go through `config.get_settings()`.
- Do not add dependencies without discussion. In particular not `keyring`,
  `GitPython`, `pyotp`, `qrcode`, `pillow` or `opencv`: an earlier version of
  this file prescribed all of them and none were ever used.

## Commands

`make help` lists them. `make check` runs lint, format and types via pre-commit;
`make test` runs the suite headless under xvfb.

There is no CI. `make sync` installs the pre-commit hook (`make hooks` on its
own if the environment already exists), and that hook is the only thing that
runs the checks without being asked. An unformatted commit has landed before
because the hook was never installed.

`uv run` outside the Makefile re-resolves the environment and tries to build
PyGObject and pycairo, which fails. Set `UV_NO_SYNC=1`, as the Makefile does.
