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
covered by a test suite. It is not packaged or released, and there is no
installable build yet.

What works today:

- Configuring several backends at once, each with its own settings
- Browsing entries as a tree, grouped by backend, folders nested by path
- Opening an entry: decrypted off the UI thread, shown with its username, URL
  and notes picked out
- Copying a field, with the clipboard cleared again after a timeout
- Editing an entry and writing it back through its backend

What does not exist yet: adding and deleting entries from the UI, working
search (the box is there, nothing is wired to it), and the "show hidden
passwords" preference. See [ROADMAP.md](ROADMAP.md).

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

- Python 3.10+
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

`make help` lists the rest.

## Working on it

Read [AGENTS.md](AGENTS.md) first — it is short, and the first rule in it
matters more than the others: **development code must never read your real
password store.** [ARCHITECTURE.md](ARCHITECTURE.md) describes how the pieces
fit together.

## Compatibility

The Direct GPG and Pass backends use the passwordstore format, so a store stays
readable by `pass`, qtpass, and Android Password Store via git sync. Extensions
such as `pass-otp` are not supported: GTKPass shows an OTP secret as the text
it is, and does not generate codes.

## Security

- Entries are decrypted only when opened, and the plaintext is dropped when the
  view moves on
- Decrypted content is kept out of logs, reprs and assertion diffs on purpose
- The clipboard is cleared after a configurable delay, as damage limitation
  rather than a guarantee — see [SECURITY.md](SECURITY.md)
- Development and test code is blocked from opening the real store

## Documentation

- [AGENTS.md](AGENTS.md) — how to work on this project
- [ARCHITECTURE.md](ARCHITECTURE.md) — how it is put together
- [ROADMAP.md](ROADMAP.md) — what is done and what is next
- [SECURITY.md](SECURITY.md) — threat model and reporting
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution guidelines

## License

MPL-2.0. See [LICENSE](LICENSE).

## Acknowledgments

- [passwordstore](https://www.passwordstore.org/) — the original `pass`
- [qtpass](https://qtpass.org/) — the inspiration
