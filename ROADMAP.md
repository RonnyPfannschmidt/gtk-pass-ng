# GTKPass Roadmap

What is built, what is next, and what is not going to happen. The previous
version of this file was a week-by-week plan for a different, much larger
application; none of its dates survived contact with the work.

## Done

**Foundation**
- Project structure, `pyproject.toml`, uv-managed environment
- Ruff, mypy and pre-commit, run by `make check` and by a git hook
- Test suite, run headless by `make test`
- CI: lint, format, types and the suite over two Fedora releases, plus building
  the RPM, installing it, and smoke testing the installed copy
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
- Search over the tree, as you type or on Enter, as the preference says
- Detail pane: username, URL and notes picked out of the entry
- Decryption off the UI thread, with stale results discarded
- Copy to clipboard, cleared again after a timeout
- Adding an entry, with a generated password: `secrets`, no dependency, and no
  characters that cost a retype when read off one screen and typed into another
- Three generation schemes -- random characters, a diceware passphrase off the
  EFF list, and digits -- offered wherever a password is set, with the entropy
  of each shown so that twenty characters and six words can be compared
- Renaming and moving, which are one operation: an entry's name is its path,
  so `pass mv` is what both go through, and the sidebar is listed again rather
  than relabelled -- a move empties the folder it left and makes the one it
  went to
- Moving a whole folder, refused as a whole if any entry under it would clash,
  because half a folder moved is a folder in two places with nothing to say
  which half went
- Editing an entry and writing it back through its backend
- Rotating an entry, in the order that cannot lose an account: make the
  replacement, take it to the site, and write the store only once somebody says
  the change took -- the editor writes first and leaves a store holding a
  password the site refused
- Deleting an entry, after a question that names it and the store it leaves
- A context menu on the sidebar rows, reached by right-click or press-and-hold,
  and a different one for an entry, a folder and a store
- An accelerator for every action, and a window that documents them
- Enter on an entry copies its password, typing anywhere searches, and Down
  leaves the search box for the rows it narrowed
- Username and URL as rows of their own in the add and edit dialogs, lifted
  out of the text on the way in and put back where they were on the way out
- The pane names the store an entry is in, shows when it last changed, and
  opens its site in the browser
- Every placeholder page offers the way out of it: Add Password, Try Again,
  the reason a store did not load with Preferences beside it
- Showing a password rather than dotting it out, from the preference
- A breakpoint, so the window works at the 360 points its metadata claims
- The store that is already there offered on first run, rather than a combo box
  of four backend type names
- Syncing a git-backed store: pull with rebase, then push, off the UI thread;
  one store from its row, all of them from the header, or at startup from a
  preference that is off by default
- What a store still has to push, counted off the UI thread and shown beside
  its name

**Hardening**
- The window opens at the size it was left at, and no schema key is offered that
  nothing reads -- a test now fails on one
- A settings write that changes nothing is not made, and a burst of writes
  costs one rebuild of the backends: the keyfile backend reports every write,
  and a row that saved per keystroke rebuilt every backend per keystroke
- Every subprocess GTKPass owns has a deadline, and the pool is never joined
  from the UI thread, so a passphrase prompt nobody answers cannot freeze or
  trap the application
- Backends are built and listed off the UI thread, so the window appears before
  a store on a dead mount has answered
- One lock per backend, so a save cannot collide with a sync in the same store
- Entry writes are atomic: a failed encryption costs the edit, not the entry
- Entry names reach `pass` after a `--`, so a name beginning with a dash is a
  path rather than a flag
- A copied secret is marked so clipboard managers do not record it, and is taken
  back on navigation and at quit
- A store whose `.gpg-id` no longer matches the approved recipient set is not
  written to until somebody has reviewed the change; GTKPass never re-encrypts
- The test suite uses its own X server and bus, never the developer's session

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
- An RPM for Fedora, and a systemd-sysext image for the ostree desktops, both
  built in a container so packaging costs the developer no layered packages;
  see [docs/PACKAGING.md](docs/PACKAGING.md)
- A .deb for Debian trixie and Ubuntu 26.04, built from the same sdist and
  tested installed on both; see [docs/DEBIAN.md](docs/DEBIAN.md)
- No launcher script in any of them: an installed build refuses nothing and
  needs nothing set, because the store guard asks whether it is running from a
  checkout rather than waiting to be told
- One-time codes from the `otpauth://` line `pass-otp` writes, with the seconds
  the code has left, computed in `otp.py` from RFC 6238 over `hmac` and checked
  against the vectors in the RFC. The line stays in the entry, so the store is
  still a `pass-otp` store; counter-based (HOTP) URIs say they are unsupported
  rather than handing out a code whose counter nothing writes back

## Next

Roughly in the order that would make the application usable day to day.

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
- **Merging the sysext image in CI.** It is built and inspected there, and
  `make sysext-test` merges it on a real machine — but `systemd-sysext merge`
  needs a running systemd and a writable `/run`, which a container has neither
  of, so nothing does it automatically.

Smaller things, worth doing when passing:

- `examples/` is stale: an old application id, and a `SettingsWindow` call that
  no longer matches the class.
- Nothing is translated. Blueprint marks its strings with `_()`, but there is no
  `po/`, nothing calls `bindtextdomain`, and every string built in Python -- all
  the toasts, all the placeholder titles -- is unmarked. Either wire gettext up
  or stop marking, because the half-measure reads as translatable and is not.
- `Gtk.ShortcutsWindow` is deprecated as of GTK 4.18. `Adw.ShortcutsDialog`
  replaces it and needs libadwaita 1.8, which is newer than this supports.
- `secretstorage` is not in the Flatpak, so the Secret Service backend reports
  itself unavailable there. It needs `cryptography`, which is a Rust build.
- Neither the RPM nor the sysext image is signed, and there is no repository to
  install either from. A release attaches them to a GitHub page, which is
  transport security and not provenance.
- The PyPI name `gtkpass` belongs to an unrelated project, and `gtk-pass` was
  refused as too similar to it, so this is distributed as `gtk-pass-ng`.
  Claiming the original is a PEP 541 request.

## Not planned

Ruled out, and listed here so they stop being proposed:

- QR codes: generating them, and scanning them from a webcam or an image
- Storing GPG passphrases in a keyring
- Password health dashboards, age tracking, duplicate detection
- A git interface of its own: branches, history, diffs, conflict resolution.
  Sync is one button that pulls and pushes; a conflict is reported and handed
  back to git, because the files are ciphertext and there is nothing useful to
  show or merge.

Two entries have left this list, and both for the same reason: the line they
drew turned out to be in the wrong place.

"Git integration beyond what `pass(1)` does by itself" went when sync landed.
`pass git push` is something `pass(1)` does by itself, while `DirectBackend` —
which writes `.gpg` files without `pass` — committed nothing at all, so a store
it wrote drifted out of step with its own history. Both now commit, and both
offer the same one-button sync.

"OTP generation" went because it was ruled out together with QR codes, which
are the part that would have cost a webcam, an image decoder and two
dependencies to match. Reading an `otpauth://` line an entry already contains
and showing a code costs none of that, and an entry a store holds that the
application will not display is a gap in the frontend rather than a decision.
It has since landed, and QR codes stay out.

The original specification prescribed `keyring`, `GitPython`, `pyotp`, `qrcode`,
`pillow` and `opencv` as dependencies. None were ever used, and OTP did not
admit one either: it is RFC 6238 over the standard library. See
[AGENTS.md](AGENTS.md).

## Versioning

No release has been made. Version numbers come from the git tags via
`setuptools-scm`, and `packaging/build-rpm.sh` derives the RPM's version and
release from the same tags, so there is nothing to keep in step by hand.
Tagging is what publishes; see [docs/RELEASING.md](docs/RELEASING.md).
