# Questions about GTKPass

## What is it?

A GTK4/Libadwaita frontend for password stores on GNOME/Linux, in the spirit of
qtpass. It is not a password manager of its own: it stores nothing and owns no
format. Backends do that, and one of them reads and writes the standard
[passwordstore](https://www.passwordstore.org/) layout.

## Can I use it yet?

Only if you are willing to build it yourself. There is no release and no
repository to install from. The application runs, browses, decrypts, edits and
syncs; [ROADMAP.md](ROADMAP.md) is the honest account of what is still missing.

## Will it work with my existing password store?

Yes. The Direct GPG and Pass backends use the passwordstore layout, so a store
stays readable by `pass`, qtpass and Android Password Store, and GTKPass can be
used alongside them on the same store or the same git repository.

## Why not just use qtpass?

Use qtpass if you want something finished — it is mature, cross-platform, and
does more than GTKPass does today. GTKPass exists because a GNOME desktop
deserves a frontend that looks and behaves like the rest of it, and because a
pluggable backend contract lets one application show a passwordstore and a
keyring side by side.

## Which backends are there?

Four in the tree: Direct GPG (reads and writes `.gpg` files itself), Pass
(delegates to the `pass` executable), Secret Service (the D-Bus keyring), and
Demo (invented entries, read-only, for trying the interface out). Several can be
configured at once, each with its own settings and name.

Backends are discovered through the `gtkpass.backends` entry point group, so one
can be shipped from another package entirely.

## What about pass extensions — pass-otp and the rest?

They are on the way. `pass-otp` and `pass-update` are the two GTKPass intends to
support; until that lands an OTP secret in a store is shown as the text it is,
and no code is generated from it. Other extensions are a case-by-case question:
some describe a storage convention that a frontend can read, and some replace
how the store works altogether.

## Can it store my GPG passphrase in the keyring?

No, and that is not planned. `gpg-agent` caches passphrases, and it is the right
place for it. The Secret Service backend does something different: it reads and
writes keyring entries as password entries in their own right.

## What about git?

A store that is a git repository is committed to on every write — by `pass`
itself, or by GTKPass for stores it writes directly — and one button pulls with
rebase and then pushes, off the UI thread.

Anything beyond that is not planned: no branches, no history browsing, no diffs,
no conflict resolution. The files are ciphertext, so there is nothing useful to
show or merge; a conflict is reported and handed back to git.

## Does it lock itself after a while?

No. Session locking and auto-lock do not exist. The GSettings schema carries an
`auto-lock-timeout` key that nothing reads — do not take it as evidence
otherwise.

## How safe is the clipboard?

Copying a field clears it again after a configurable delay. Treat that as damage
limitation rather than a guarantee: a clipboard manager may already have taken a
copy, and a Wayland compositor may refuse a clear requested by an application
that is not focused. [SECURITY.md](SECURITY.md) is explicit about what is and is
not protected.

## Does it phone home?

No telemetry, no analytics, no external connections. The only network access is
git sync against the remote you configured.

## What do I need to run it?

Python 3.11+, GTK4 4.10+, Libadwaita 1.4+, PyGObject and pycairo from your
distribution rather than PyPI, and GnuPG 2.x for the GPG-backed stores. Then
`make sync` and `make run`; see [DEVELOPMENT.md](DEVELOPMENT.md).

## How do I install it?

Three routes, all built from a checkout and none of them released:

- `make flatpak` — bundles `pass`, `tree` and git so the sandbox needs no host
  access; see [docs/FLATPAK.md](docs/FLATPAK.md)
- `make rpm` — an RPM for a package-based Fedora
- `make sysext` — a systemd-sysext image for Bluefin, Silverblue and the other
  ostree desktops, where a package would mean rebuilding the deployment

The last two are covered in [docs/PACKAGING.md](docs/PACKAGING.md). Nothing is
on Flathub or in a repository, and nothing is signed.

## Which distributions does it work on?

Any with a new enough GTK4 and Libadwaita. It is developed on Bluefin and has
not been tested broadly. Linux only: Windows and macOS are not planned.

## I want to help — where do I start?

[AGENTS.md](AGENTS.md), which is short, and whose first rule matters more than
the rest: development code must never read your real password store. Then
[DEVELOPMENT.md](DEVELOPMENT.md) for the setup and
[CONTRIBUTING.md](CONTRIBUTING.md) for how a change gets in.

## Something is broken. Where do I report it?

[GitHub issues](https://github.com/RonnyPfannschmidt/gtkpass/issues), with your
distribution, GTK version and Python version, and what you did. Never paste a
decrypted entry into one. For anything with security impact, read the reporting
section of [SECURITY.md](SECURITY.md) first.

## Who maintains it, and under what licence?

Ronny Pfannschmidt ([@RonnyPfannschmidt](https://github.com/RonnyPfannschmidt)),
under MPL-2.0. The project is independent of `pass` and of qtpass.
