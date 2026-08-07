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
- Showing a password rather than dotting it out, from the preference
- Syncing a git-backed store: pull with rebase, then push, off the UI thread

**Host integration**
- Every write to a git-backed store is committed, by `pass` or by GTKPass
- Sandbox permissions read from `/.flatpak-info` rather than guessed from the
  environment, so the application can say what is missing and how to grant it
- SSH agent and network access left to `flatpak override` instead of requested
  for everyone; see [docs/FLATPAK.md](docs/FLATPAK.md)

**Packaging**
- Desktop entry, AppStream component and icon, all named after the app id and
  held to it by a test
- A Flatpak that builds and installs, bundling pass, tree and git so the
  sandbox needs no host access; see [docs/FLATPAK.md](docs/FLATPAK.md)

## Next

Roughly in the order that would make the application usable day to day.

- **Search.** The entry box sits in the sidebar and nothing is connected to it,
  so typing does nothing at all. The tree is already in memory, so this is a
  filter over the model rather than backend work.
- **Adding an entry.** The `+` button still opens a "not implemented" dialog.
  The backends implement `add_password`; the dialog is most of what is missing.
- **Deleting an entry**, with a confirmation, and pruning the emptied folders.
- **Renaming and moving**, on top of `move_password`.
- **Password generation** when adding an entry.
- **Re-encrypting a store to a changed recipient set**, which `pass init
  <ids...>` does and GTKPass cannot. Multi-recipient stores already work, so a
  per-machine key model is adoptable today — but enrolling a machine or retiring
  one means leaving the application, which is the whole administrative half of
  it. Showing who a store is currently encrypted to belongs with it; a stale
  recipient is otherwise invisible. See
  [docs/TRUST-MODEL.md](docs/TRUST-MODEL.md).
- **Submitting to Flathub.** The Flatpak builds locally but is not release
  ready: no screenshots, no release tag, a placeholder icon and a manifest that
  builds from the working directory. See
  [docs/FLATHUB.md](docs/FLATHUB.md).
- **CI.** There is none. `make check` and `make test` are the entire gate, and
  they only run when someone remembers.

Smaller things, worth doing when passing:

- `examples/` is stale: an old application id, and a `SettingsWindow` call that
  no longer matches the class.
- `secretstorage` is not in the Flatpak, so the Secret Service backend reports
  itself unavailable there. It needs `cryptography`, which is a Rust build.

## Not planned

Ruled out, and listed here so they stop being proposed:

- OTP generation and QR codes
- Storing GPG passphrases in a keyring
- Password health dashboards, age tracking, duplicate detection
- A git interface of its own: branches, history, diffs, conflict resolution.
  Sync is one button that pulls and pushes; a conflict is reported and handed
  back to git, because the files are ciphertext and there is nothing useful to
  show or merge.

"Git integration beyond what `pass(1)` does by itself" used to be on this list.
It moved because sync landed, and the line it drew turned out to be in an odd
place: `pass git push` is something `pass(1)` does by itself, while
`DirectBackend` — which writes `.gpg` files without `pass` — committed nothing
at all, so a store it wrote drifted out of step with its own history. Both now
commit, and both offer the same one-button sync.

These came from the original specification, which also prescribed `keyring`,
`GitPython`, `pyotp`, `qrcode`, `pillow` and `opencv` as dependencies. None
were ever used. Adding any of it back is a discussion first, not a pull
request; see [AGENTS.md](AGENTS.md).

## Versioning

No release has been made. Version numbers come from the git tags via
`setuptools-scm`, so there is nothing to keep in step by hand.
