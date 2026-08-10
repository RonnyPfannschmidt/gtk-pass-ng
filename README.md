# GTKPass

A GTK4/Libadwaita frontend for password stores on GNOME/Linux, in the spirit of
qtpass.

## Overview

GTKPass is not a password manager of its own: it stores nothing and owns no
format. It is a native GTK4 interface over pluggable backends, one of which
reads and writes the standard [passwordstore](https://www.passwordstore.org/)
layout, so an existing store stays usable from `pass` and every other tool that
speaks it.

## Status

**Early, and honest about it.** The application runs, reads and edits, and is
covered by a test suite. It builds as a Flatpak, an RPM and a systemd-sysext
image — but nothing is released, signed, or installable from a repository.

What works today:

- Configuring several backends at once, each with its own settings
- Browsing entries as a tree, grouped by backend, folders nested by path
- Opening an entry: decrypted off the UI thread, and every field it carries
  shown, whether or not GTKPass knows what the field means
- Copying a field, with the clipboard cleared again after a timeout
- Editing an entry and writing it back through its backend
- Syncing a git-backed store: pull with rebase, then push, off the UI thread

What does not exist yet: adding and deleting entries from the UI, and search —
the box is in the sidebar, and nothing is wired to it. See
[ROADMAP.md](ROADMAP.md).

## Backends

| Backend | Reads | Writes | Notes |
| --- | --- | --- | --- |
| Direct GPG | yes | yes | GPG-encrypted files, handled natively |
| Pass | yes | yes | delegates to the `pass` executable |
| Secret Service | yes | yes | the D-Bus keyring service |
| Demo | yes | no | invented entries, for trying the UI out |

Backends are discovered through the `gtkpass.backends` entry point group, so
one can be shipped separately from this repository.

## Requirements

- Python 3.11+
- GTK4 4.10+ and Libadwaita 1.4+
- PyGObject and pycairo, from your distribution rather than from PyPI
- GnuPG 2.x, for the GPG-backed stores

## Running it

There is no release to install. From a checkout:

```bash
make sync      # environment, dependencies and the git hooks
make run       # launch against your real password store
```

To try it out without touching your own passwords:

```bash
make run-dev   # a throwaway store of invented entries under .dev/
```

Or build something installable, none of it released or signed:

```bash
make flatpak   # see docs/FLATPAK.md
make rpm       # an RPM for Fedora
make sysext    # a systemd-sysext image for Bluefin, Silverblue and the rest
```

`make help` lists the rest, and [docs/PACKAGING.md](docs/PACKAGING.md) covers
the last two.

## Working on it

Read [AGENTS.md](AGENTS.md) first — it is short, and the first rule in it
matters more than the others: **development code must never read your real
password store.** [ARCHITECTURE.md](ARCHITECTURE.md) describes how the pieces
fit together.

## Compatibility

The Direct GPG and Pass backends use the passwordstore format, so a store stays
readable by `pass`, qtpass, and Android Password Store via git sync. Extensions
are not supported yet — `pass-otp` and `pass-update` are the two intended, and
until they land an OTP secret is shown as the text it is rather than turned into
a code.

## Security

- Entries are decrypted only when opened, and the plaintext is dropped when the
  view moves on
- Decrypted content is kept out of logs, reprs and assertion diffs on purpose
- The clipboard is cleared after a configurable delay, as damage limitation
  rather than a guarantee — see [SECURITY.md](SECURITY.md)
- Code running out of a checkout is blocked from opening the real store or the
  keyring, so development and test runs cannot read real passwords

## Documentation

- [FAQ.md](FAQ.md) — the short answers
- [AGENTS.md](AGENTS.md) — how to work on this project
- [ARCHITECTURE.md](ARCHITECTURE.md) — how it is put together
- [ROADMAP.md](ROADMAP.md) — what is done and what is next
- [SECURITY.md](SECURITY.md) — threat model and reporting
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution guidelines
- [docs/PACKAGING.md](docs/PACKAGING.md) — the RPM and the sysext image
- [docs/FLATPAK.md](docs/FLATPAK.md) — the Flatpak, and its sandbox permissions
- [docs/FLATHUB.md](docs/FLATHUB.md) — what publishing it would take
- [docs/TRUST-MODEL.md](docs/TRUST-MODEL.md) — per-machine keys, and what
  decryption costs

## License

MPL-2.0. See [LICENSE](LICENSE).

## Acknowledgments

- [passwordstore](https://www.passwordstore.org/) — the original `pass`
- [qtpass](https://qtpass.org/) — the inspiration
