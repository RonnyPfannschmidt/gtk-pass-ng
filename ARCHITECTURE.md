# GTKPass Architecture

GTKPass is a GTK4/Libadwaita frontend over pluggable password backends. It is
not a password manager of its own: it stores nothing, encrypts nothing, and
owns no format. A backend does that, and GTKPass shows the result.

This document describes the code as it stands. Where something is deliberately
absent, that is said outright rather than left to look like an omission.

## Module map

```
src/gtkpass/
├── __main__.py          entry point; calls app.main()
├── app.py               GTKPassApp (Adw.Application): actions, CLI options
├── window.py            GTKPassWindow: backends, sidebar, detail pane, editing
├── config.py            application identity, GSettings access, schema lookup
├── safety.py            keeps checkout code out of the real store
├── sandbox.py           what the Flatpak sandbox actually permits
├── frozen.py            what a PyInstaller bundle has to arrange for itself
├── _gi.py               the one place gi.require_version is called
├── backends/
│   ├── __init__.py      the backend contract: PasswordBackend and its data
│   ├── manager.py       discovery, instances, and the worker thread pool
│   ├── serialized.py    the proxy that keeps one backend to one call at a time
│   ├── recipients.py    who a store is encrypted to, and whether that changed
│   ├── git_store.py     the only thing in the tree that runs git
│   ├── demo.py          invented entries, read-only
│   ├── direct.py        GPG-encrypted files, read and written natively
│   ├── pass_cli.py      delegates to the pass(1) executable
│   ├── secretservice.py the D-Bus Secret Service (keyrings)
│   └── data/demo.json   the invented entries themselves
├── ui/
│   ├── blueprints/      *.blp sources and their compiled *.ui
│   ├── password_list.py the sidebar tree
│   ├── password_detail.py  the pane showing one decrypted entry
│   ├── password_edit.py    the edit dialog
│   ├── settings.py      preferences, including configuring backends
│   └── about.py
└── utils/
    ├── async_ui.py      moving worker results onto the UI thread
    └── clipboard.py     copying a secret and taking it back out
```

## Identity and settings

Every identifier the desktop cares about — the D-Bus name, the `.desktop` file,
the icon, the AppStream component, the GSettings schema — has to be the same
string, so `config.py` defines `APP_ID` once and derives the rest from it.

Settings are reached through `config.get_settings()` and
`config.get_backend_settings()`, never through `Gio.Settings.new()` directly:
that function calls `g_error()` on a schema it cannot find, which aborts the
process with no traceback. The helpers look the schema up first and raise
`SchemaNotInstalledError` instead.

Where they look is `config.schema_source()`, which is GLib's default source plus
`/usr/share/gtkpass/schemas` when that exists. Only the systemd-sysext image
ships such a directory, and it has to: the system `gschemas.compiled` is one
file holding every application's schemas, and an overlay carrying its own copy
would hide all of them. Adding to the search path rather than replacing it keeps
the RPM and a checkout unaffected, and an unreadable directory there is logged
and ignored rather than allowed to abort startup. See
[docs/PACKAGING.md](docs/PACKAGING.md).

Each configured backend instance gets its own settings, stored under a
*relocatable* schema at `/io/github/RonnyPfannschmidt/GTKPass/backends/<id>/`.
The top level schema holds only the list of instances, as `(id, type)` pairs,
plus the application's own preferences.

## Backends

`backends/__init__.py` is the contract. It defines:

- **`PasswordBackend`**, the abstract base. Classmethods `is_available()` and
  `create(settings)`; instance methods `list_passwords()`, `get_password()`,
  `search()`, and the writes `add_password()`, `edit_password()`,
  `delete_password()`, `move_password()`, `copy_password()`.
- **`PasswordMetadata`** — what listing returns: name, path, mtime. No secret.
- **`PasswordEntry`** — one entry, with `content` once it has been decrypted.
  Its `password` property is the first line and `metadata` the `key: value`
  lines after it. Its `repr` is redacted deliberately; see *Handling secrets*.
- **`BackendSettings`**, subclassed per backend for its own configuration.
- **`BackendError`** and the more specific `GPGError`, `GitError` and
  `RecipientsChanged`.
- **`recipient_audit()`**, answered from what the backend read when it was
  built. Not abstract: a backend with no `.gpg-id` — the keyring, the demo data
  — returns None, and making it abstract would force every one of them, and
  every third-party backend, to write a stub saying so.

Backends are discovered through the `gtkpass.backends` entry point group, which
is what makes them pluggable: a backend shipped by another distribution needs
no change here. The four in-tree ones are registered in `pyproject.toml`.

`BackendManager` owns discovery and the live instances, keyed by instance id.
**Nothing outside `manager.py` imports a backend module directly** — the window
asks the manager, and the manager holds the only references.

What it hands out is a `SerializedBackend`, not the backend itself. Four workers
share every instance, and no backend is written for that: the file backends each
own one `GitStore` over one directory, so a commit landing during a `pull
--rebase` collides on `.git/index.lock`; the Secret Service backend shares a
single D-Bus connection; and a decrypt reading a `.gpg` file during a rebase can
read half of another revision. The proxy holds one lock per backend — per
backend rather than per manager, so a store on a slow mount does not hold up an
unrelated one. `sync_capability()`, `recipient_audit()` and `metadata` stay
outside it: they answer out of state fixed at construction and are read on the
UI thread.

`backends/recipients.py` reads a store's `.gpg-id` files and compares them with
the set last approved for that instance. It is the answer to a question sync
introduced: whoever can write to a remote can add a recipient, and every entry
saved afterwards is encrypted to them. What they cannot do is re-encrypt the
entries already there, which would mean decrypting them first — so an entry left
on the old recipients is evidence about who made the change. A store whose
recipients differ from the record is not written to until somebody accepts it,
and accepting records the new set and nothing else. **GTKPass never
re-encrypts**: that is `pass init <ids...>`, and doing it here on the strength of
the file under suspicion would hand out copies of every entry the changer could
not read.

The conformance suite in `tests/test_backend_contract.py` is the definition of
done for backend work: a new backend is finished when it passes.

## User interface

Widgets are declared in `ui/blueprints/*.blp` and loaded as templates. The
`.ui` files beside them are generated by `make ui` and must never be hand
edited. `tests/test_ui_is_declarative.py` fails on widget construction in
Python, so a widget tree that drifts out of Blueprint is caught rather than
merely discouraged.

**The window** loads the configured backends at startup, lists each one in the
sidebar, and records those that failed so they can be shown as unavailable
rather than silently missing.

**The sidebar** (`password_list.py`) is a `Gtk.ColumnView` over a
`Gtk.TreeListModel` of `PasswordNode` objects — a backend, a folder, or an
entry. Path components become folders, so `work/mail/imap` nests three deep.
Every node carries the id of the backend it belongs to, so a selected entry
names its own backend without a walk back up the tree. The row itself is
declared in the Blueprint as a `BuilderListItemFactory` template, which is why
the binding expressions there cast to `$GTKPassPasswordNode`.

**The detail pane** (`password_detail.py`) shows one decrypted entry. It has
rows of its own for the fields it understands — the password, and the
username and URL under whichever of their several conventional spellings the
store used — and renders everything else as the key and value it was written as.
A store carries whatever its owner put there, and an entry with a field GTKPass
has no opinion about is not a reason to hide it.

Fields whose *name* says they are secrets — `otp`, `pin`, `recovery` and the
rest of `SENSITIVE_KEYS` — are dotted out like the password, with one control on
the group that shows them. One control rather than one per row because a
`BuilderListItemFactory` template cannot connect a signal, there being no object
to connect it to, and `action-target` takes a `GVariant` that a string property
cannot be bound to. The row binds `display`, which the item recomputes and
notifies when it is revealed.

It emits `copy-requested` instead of touching the clipboard, leaving the window
to apply the user's timeout and raise the toast.

**The edit dialog** splits an entry into the password and everything after it,
and joins the two back on save. It never reserialises the fields it parsed:
what it hands over replaces the entry wholesale, so anything dropped on the way
would be lost.

## Threads

GPG is slow and `pass` is a subprocess, so backend calls do not run on the UI
thread. `BackendManager` owns a `ThreadPoolExecutor` and returns futures from
`list_passwords_async()`, `get_password_async()`, `edit_password_async()` and
`sync_async()`, plus a bare `submit()` for work that is not a backend call yet.

*Building* a backend goes through that pool as well. A constructor runs three
git commands over the store, and the Secret Service one opens a D-Bus
connection, waits up to five seconds for an answer and may unlock a collection —
all of which used to happen inside `GTKPassWindow.__init__`, so the window did
not appear until every configured backend had answered, and for a store on a
mount that had gone away it never did.

Nothing on that pool can run forever. Every subprocess GTKPass owns is bounded
by `SUBPROCESS_TIMEOUT_SECONDS`, and `shutdown()` does not wait: it is called
from the UI thread at quit and on every settings change, so joining the pool
there meant one worker sitting on an unanswered passphrase prompt froze the
window. Both halves are needed — the interpreter still joins the pool's threads
at exit, so a command with no deadline would keep the process alive whatever
`shutdown()` does.

`utils/async_ui.on_ui_thread()` is the single place a result crosses back.
`Future.add_done_callback` runs on the worker, and touching a widget from there
corrupts GTK state in ways that surface much later, so the callback only
schedules a `GLib.idle_add`.

Selection carries a request counter. Arrow-keying down the sidebar starts one
decrypt per row, and a slow one landing after a later selection would otherwise
replace an entry the user has already moved off; a result whose number is stale
is dropped.

## Data flow

**Startup.** `main()` → `GTKPassApp.do_activate()` → `GTKPassWindow`, which
reads `backend-instances` from GSettings on the UI thread — dconf lookups, and
the change handlers live there — and then hands the constructing to the pool.
When the backends land they are installed, and each is asked for its entries
separately, so the sidebar fills in per backend rather than all at once. Two
request counters guard the results: a load superseded by a settings change is
not installed into a manager that has since been shut down, and a listing from
the previous configuration cannot append to the tree the new one is building.
With nothing configured, the window shows a prompt pointing at Preferences
instead of an empty tree.

**Opening an entry.** Selecting a row calls `get_password_async()`; the pane
shows a spinner, then the decrypted entry when the future lands, or a toast if
it fails.

**Editing an entry.** The dialog emits `saved` with the replacement content,
the window puts it through `edit_password_async()`, and on success reads the
entry back from the store rather than trusting the widgets — which is also what
proves the write landed.

## Storage format

The `pass` convention, which the file backends follow: the first line is the
password, and the lines after it are free text, conventionally `key: value`.
GTKPass reads `username`/`user`/`login` and `url`/`website`/`uri` out of it for
display, and treats anything else as notes. It does not impose a schema, and an
entry it did not understand is preserved verbatim through an edit.

## Handling secrets

The rules are in [AGENTS.md](AGENTS.md); the mechanisms are here.

- `safety.py` refuses `~/.password-store`, `$PASSWORD_STORE_DIR` and the
  session keyring when the code is running out of a checkout.
  `running_from_checkout()` asks the installed distribution rather than the
  filesystem layout: an editable install records `dir_info.editable` in its
  `direct_url.json` (PEP 610), which pip and uv both write, and which states
  the fact instead of implying it. Two things qualify that answer. The metadata
  is believed only when it *describes the module that is running*, so a checkout
  ahead of an installed release on `sys.path` is a checkout rather than an
  installed build on the strength of the other copy's metadata. And a
  `.egg-info` is not an install: setuptools leaves one in the source tree, it
  satisfies `importlib.metadata`, and it has no `direct_url.json` — so it read
  as an ordinary packaged install until it was excluded.

  An installed build is allowed, because the alternative is every package
  shipping a launcher script to undo the guard, and a wrapper that exists to
  disable a safety check is one nobody reads twice.
  `GTKPASS_ALLOW_REAL_STORE` overrides both ways; `run_app.sh` sets it to 1, and
  the test suite clears it so an exported value cannot re-enable it for a run.
- `safety.require_installed()` runs on import of `gtkpass` and refuses a process
  that was never installed. A `PYTHONPATH=src` run has no metadata, so nothing
  about it can be established — not its version, and not whether it is somebody's
  working copy. Failing at import with a message naming `make sync` is better
  than carrying a fourth case through every question above.
- A store carrying a `.gtkpass-scratch-store` marker is not treated as real,
  which is how `make run-dev` opens its own throwaway store without disabling
  the guard for everything else. The default store location cannot be marked.
- The keyring has no scratch equivalent: the Secret Service is whichever one
  the session bus offers, so `is_available()` reports unavailable rather than
  probing it, and `create()` refuses.
- `PasswordEntry.__repr__` is redacted and `content` is excluded from it. The
  generated dataclass repr would have put plaintext into every log line,
  traceback and pytest assertion diff that rendered an entry.
- `PasswordEntry.clear_password()` drops the plaintext when the pane moves on.
- `ClipboardCopier` offers `x-kde-passwordManagerHint` alongside the text, which
  is what asks a clipboard manager not to record the copy. There is no
  specification for that type; the spelling is Klipper's and it is what the
  other password managers offer, which makes it the convention by use. It
  matters more than the timeout does: a manager takes its copy the moment the
  selection changes, so by the time a timer fires the password is already in a
  history that outlives it. Not everything copied is marked — the sync dialog
  offers a shell command, which belongs in the history.
- The copy is also taken back when the detail pane moves to another entry, and
  when the application quits, since a GLib timeout cannot fire in a process that
  has exited. The first keeps the read-back check, so it can only remove what
  GTKPass put there; the one at shutdown cannot, there being no main loop left
  to deliver the answer to. Clearing is still damage limitation rather than a
  guarantee: a manager that ignores the hint has its copy, and a Wayland
  compositor may refuse a clear from an unfocused application.
- `DirectBackend` builds ciphertext beside the entry and moves it over with
  `os.replace`. `gpg --output` is opened for writing before gpg knows whether it
  can encrypt, so writing in place meant an unusable recipient or a full disk
  left the entry existing and empty — with no undo, and no history in a store
  that is not a repository.

## What is deliberately absent

An earlier design described OTP, QR code, Git and keyring *services*, and
prescribed the dependencies to build them — `keyring`, `GitPython`, `pyotp`,
`qrcode`, `pillow`, `opencv`. None were ever written and none are planned.

Git is handled by `backends/git_store.py`, a plain `GitStore` object owned by a
backend instance rather than a mixin on `PasswordBackend`. It is the only thing
in the tree that runs `git`, and it never encrypts or decrypts: by the time it
sees a store, the store holds `.gpg` ciphertext and its inputs are file paths
and a commit message. That is what lets its failure-mode tests run with no GPG
key, no `pass` and no backend at all.

The `commit` flag is now acted on, and the two filesystem backends differ in a
way worth stating. `DirectBackend` writes `.gpg` files itself and so commits
them itself; it constructs its `GitStore` with `commit_on_write=True` and
honours `commit=False`. `PassBackend` constructs one with
`commit_on_write=False` and never calls `commit()`, because `pass insert`, `rm`,
`mv` and `cp` each commit internally whenever the store is a repository — a
second commit would be an empty one after every write. `PassBackend` cannot
honour `commit=False` either: `pass` decides, and there is no environment
variable for it.

`sync_capability()` and `sync()` are non-abstract on the contract. A backend
with no filesystem store — the keyring, the demo data — inherits a default that
says so, rather than every implementation writing a stub. The capability is
probed once when a backend is created, because the window reads it on the UI
thread to decide whether the sync button is sensitive.

`src/gtkpass/sandbox.py` sits beside `safety.py` and answers what the Flatpak
sandbox permits, by parsing `[Context]` out of `/.flatpak-info`. Sync needs
permissions the manifest deliberately does not request, so this is what lets the
application tell the user which `flatpak override` to run instead of failing at
push time. It does **not** consult `$SSH_AUTH_SOCK`, which survives into a
sandbox that was denied the socket and therefore lies.

`make check` and `make test` run locally, the pre-commit hook installed by
`make hooks` runs the former on the way in, and `.github/workflows/ci.yml` runs
on push and pull request across two Fedora releases.

CI packages before it tests. It builds the wheel, the sdist and the RPMs, then
runs the suite against each of them *installed* -- the wheel in a virtualenv,
the RPM through `dnf install` -- rather than against the working copy, which is
a thing nobody runs. The faults that ordering catches are the ones a source-tree
run cannot see: a wheel missing its `.ui` files, a schema that never reached the
compiled cache, an entry point resolving to nothing.

The `src/` layout is what makes it honest, `import gtkpass` from the repository
root finding nothing. One consequence: the guard defaults *open* for an installed
build, so `conftest.py` sets `GTKPASS_ALLOW_REAL_STORE=0` outright rather than
clearing it, or those runs would be unguarded with every test still passing.
