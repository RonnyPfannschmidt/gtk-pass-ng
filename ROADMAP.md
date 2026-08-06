# GTKPass Roadmap

What is built, what is next, and what is not going to happen. The previous
version of this file was a week-by-week plan for a different, much larger
application; none of its dates survived contact with the work.

## Done

**Foundation**
- Project structure, `pyproject.toml`, uv-managed environment
- Ruff, mypy and pre-commit, run by `make check` and by a git hook
- Test suite, run headless by `make test`
- One canonical application identity in `config.py`
- A throwaway development store, so nothing here reads real passwords

**Backends**
- The `PasswordBackend` contract, with a conformance suite that defines done
- Discovery through the `gtkpass.backends` entry point group
- Four implementations: Direct GPG, Pass CLI, Secret Service, Demo
- Per-instance configuration in relocatable GSettings schemas
- Several backends configured at once, each named and renameable

**Interface**
- Widgets declared in Blueprint, with a test that keeps them there
- Sidebar tree over ColumnView: backends as roots, folders nested by path
- Detail pane: username, URL and notes picked out of the entry
- Decryption off the UI thread, with stale results discarded
- Copy to clipboard, cleared again after a timeout
- Editing an entry and writing it back through its backend

## Next

Roughly in the order that would make the application usable day to day.

- **Adding an entry.** The `+` button still opens a "not implemented" dialog.
  The backends implement `add_password`; the dialog is most of what is missing.
- **Deleting an entry**, with a confirmation, and pruning the emptied folders.
- **Search.** The entry box exists in the sidebar and nothing is connected to
  it. `search()` is already part of the backend contract.
- **Renaming and moving**, on top of `move_password`.
- **The "show hidden passwords" preference.** It is in the schema and in the
  settings dialog, but bound to a property `Adw.PasswordEntryRow` does not
  have, so it does nothing and logs a `GLib-GIO-CRITICAL` at startup.
- **Password generation** when adding an entry.
- **Packaging**: a Flatpak, and the desktop and AppStream metadata to go with
  it. Nothing is installable today.
- **CI.** There is none. `make check` and `make test` are the entire gate, and
  they only run when someone remembers.

## Not planned

Ruled out, and listed here so they stop being proposed:

- OTP generation and QR codes
- Git integration beyond what `pass(1)` does by itself
- Storing GPG passphrases in a keyring
- Password health dashboards, age tracking, duplicate detection

These came from the original specification, which also prescribed `keyring`,
`GitPython`, `pyotp`, `qrcode`, `pillow` and `opencv` as dependencies. None
were ever used. Adding any of it back is a discussion first, not a pull
request; see [AGENTS.md](AGENTS.md).

## Versioning

No release has been made. Version numbers come from the git tags via
`setuptools-scm`, so there is nothing to keep in step by hand.
