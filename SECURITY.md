# Security Policy

## Supported versions

None, in the sense that word usually carries. There has never been a release:
no tag, no package in any repository, nothing signed. What exists is a git
history, and the only version anyone can run is a checkout or a build made from
one.

So there is no supported branch, no backporting, and no security release
process to invoke. A fix lands on `main`, and anyone running this rebuilds.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Use [GitHub Security Advisories][advisories] on this repository, or email the
maintainer at the address in the git history. Include what you did, what
happened, and why you think it matters; a proof of concept is welcome but not
required, and please never attach a real decrypted entry.

[advisories]: https://github.com/RonnyPfannschmidt/gtk-pass-ng/security/advisories

This is one person working on this in their own time, so the honest expectation
is a reply within a week or two rather than within hours. If a report turns out
to be real, disclosure gets coordinated with whoever reported it, and they get
the credit unless they would rather not.

## What the application actually does

Anything not listed here is not implemented.

### Encryption

Encryption is the backend's job, not the application's. The Direct GPG and Pass
backends store entries as GPG-encrypted files in the passwordstore layout, so
the keys, the cipher and the recipients are GnuPG's business and yours. The
Direct backend resolves recipients from the nearest `.gpg-id` walking up from
the entry, which is what `pass` does, so a subtree delegated to another set of
recipients stays delegated. Every recipient listed there is encrypted to, which
is what makes a per-machine key model possible; what that buys, what TPM binding
does and does not protect against, and how to retire a machine without leaving
its key able to read the store are in
[docs/TRUST-MODEL.md](docs/TRUST-MODEL.md). GTKPass cannot change a store's
recipient set, so enrolling or retiring a key is still `pass init` in a
terminal.

The Secret Service backend stores nothing itself: it hands entries to the
session keyring over D-Bus. It shows the whole collection rather than only its
own items, so it can open a password another application stored — and an edit
keeps that item's own attributes, which are how its owner looks it up again.

One thing to know about it: the metadata lines of an entry it writes become
keyring *attributes*, which are lookup keys rather than part of the secret, and
are searchable over D-Bus without unlocking the item. A `pin:` or `recovery:`
line therefore ends up outside the protected part. Nothing in the interface
creates keyring entries yet, so this affects only what somebody writes there
deliberately; it should be the whole content in the secret instead.

### Who a store is encrypted to

`.gpg-id` decides who can read everything written from now on, and nothing
verifies it. That was a local question while the store was local; sync made it a
remote one, because whoever can write to the remote can add a recipient and
every entry saved afterwards is encrypted to them too.

What such a change cannot bring with it is a rekey: re-encrypting the existing
entries means decrypting them first, which is exactly what the party making the
change cannot do. So GTKPass records the recipient set each store was last
approved with — in the instance's own settings, outside the store, where a
remote cannot reach it — and compares on every load. A store whose `.gpg-id` no
longer matches is not written to until somebody has looked at what changed:
which recipients were added or removed, and which entries were left encrypted to
the old set. Reading is unaffected, because nothing newly named there can
decrypt what is already stored.

Accepting records the new set and nothing else. **GTKPass never re-encrypts.**
Rekeying a store is `pass init <ids...>`, a deliberate act by somebody who has
decided the new recipient belongs; doing it automatically on the strength of the
file under suspicion would take every entry the changer could not read and hand
them a copy they can.

A store seen for the first time is taken as it stands. Nothing here can
establish who *should* be able to read somebody's store, and refusing to write
to every existing store until it had been re-approved would only teach people to
click the button without reading it.

### Syncing with a remote

Sync is `git pull --rebase` followed by `git push`, over whatever transport the
store's remote uses. What reaches the remote is the ciphertext plus the entry
*names*, since the names are the filenames — exactly what `pass git push`
already sends. Git history also keeps the ciphertext of deleted entries. Both
are inherent to a git-backed store rather than choices GTKPass makes.

Over ssh, the remote's host key has to be known already:
`StrictHostKeyChecking=yes`, not `accept-new`. Taking whatever key answers the
first connection from a machine trusts it at exactly the moment somebody in the
way cannot be detected, and while the entries are ciphertext, the entry names
are not, and an old copy of the store served back restores a password you
rotated. So the first sync from a new machine fails, and says which host to
check the fingerprint of and what to run.

A pull that would discard local history is refused. GTKPass fetches before it
rebases and checks that the remote still contains the commit this store was last
synced with; if it does not, the sync stops and nothing here is changed. That
covers a force-pushed remote dropping entries or restoring an old copy of one,
which for a store of ciphertext leaves nothing on screen that would look wrong.
It does not cover a rollback committed forward as an ordinary change, and it is
not authentication: the remote is not asked to prove who it is beyond its host
key, and commits are neither signed nor verified.

### Handling decrypted data

- Entries are decrypted only when opened, one at a time.
- The first line is not the only field treated as a secret. A field whose name
  says its value is one — `otp`, `otpauth`, `pin`, `secret`, `token`, `key`,
  `seed`, `recovery` and a few spellings of those — is dotted out with the
  password rather than rendered as a plain label, and shown on request. It is a
  list of names rather than a guess at the value, so a field nobody thought of
  stays visible rather than a hostname being hidden.
- A write builds its ciphertext beside the entry and moves it into place, so an
  encryption that fails half way costs the edit rather than the entry. `gpg
  --output` is opened for writing before gpg knows whether it can encrypt, so
  writing in place left a truncated entry with no undo and, in a store that is
  not a repository, no history to recover from.
- The plaintext is dropped when the detail pane moves on to another entry.
- `PasswordEntry` excludes its content from its `repr`, which is redacted by
  hand. The generated dataclass repr would otherwise have put plaintext into
  every log line, traceback and test assertion diff that rendered an entry.
- Nothing logs a decrypted value.

Python cannot guarantee that a secret is gone from memory: strings are
immutable and the garbage collector may keep copies. Dropping references
reduces exposure; it does not eliminate it.

### Clipboard

A copied secret is offered with `x-kde-passwordManagerHint` alongside the text,
which is what asks a clipboard manager not to keep it. There is no specification
for that type — the spelling is Klipper's, and it is what KeePassXC and Bitwarden
offer, which makes it the convention by use rather than by agreement. A manager
that does not know it is no worse off, since the text is offered next to it.

That hint matters more than the timeout does. A clipboard manager takes its copy
the moment the selection changes, so by the time the timer fires the password is
already in a history that outlives the timer, the window and the application, and
nothing this side of the clipboard can reach into it.

The copy is taken back when the timeout expires, when the detail pane moves to
another entry, and when the application quits — the last because a timeout
cannot fire in a process that has exited. The first two check that the clipboard
still holds what GTKPass put there before clearing it; the one at shutdown
cannot, there being no main loop left to deliver that answer.

Treat all of it as damage limitation, not a guarantee: a manager that ignores the
hint has its copy, and a Wayland compositor may refuse a clear requested by an
application that is not focused.

### Development safeguards

Code running out of a checkout is blocked from opening the real store or the
keyring: the backends refuse `~/.password-store`, `$PASSWORD_STORE_DIR` and the
session Secret Service. An installed build is not blocked, because it is the
application actually being used. `GTKPASS_ALLOW_REAL_STORE` overrides the
decision in both directions, and `run_app.sh` sets it to 1 — launching a
checkout being the one case where the checkout really is the application.

This exists because a decrypted password that reaches a terminal, a CI log or an
AI assistant's transcript cannot be un-disclosed.

The development store carries a marker file that exempts it, so the guard stays
armed during a development run rather than being switched off wholesale. The
default store location cannot be exempted this way.

The test suite runs against its own X server and its own D-Bus session rather
than the one the developer is sitting in front of. GDK ignores `DISPLAY`
whenever `WAYLAND_DISPLAY` is set, and a desktop session exports
`GDK_BACKEND=wayland` itself, so `xvfb-run` alone was not enough: windows opened
on the real screen, and a clipboard test would overwrite whatever the developer
had copied — which, working on this, may well have been a password.

Note that this is a guard against mistakes by people working on GTKPass, not a
security boundary. It is an environment variable and a check on a file path:
anything running as the user can defeat either.

### Not implemented

Do not rely on any of these — they do not exist:

- Session locking or auto-lock after inactivity. The GSettings schema carries an
  `auto-lock-timeout` key that no code reads; it is not a feature, and reading
  the schema is not evidence of one.
- Storing the GPG passphrase in a keyring (GPG agent handles caching)
- Screenshot prevention
- Secure or locked memory allocation
- Signature verification, of entries or of anything else. `pass` can sign
  `.gpg-id` (`PASSWORD_STORE_SIGNING_KEY`, `.gpg-id.sig`) and GTKPass neither
  writes nor checks that signature. What it does instead is compare the
  recipient set against the one last approved, and refuse to write when they
  differ — which is a different guarantee, and a weaker one: it detects a change
  rather than proving who made it
- Signed commits, and signed packages: neither the RPM nor the sysext image is
  signed, and there is no repository to install either from

## What it cannot protect against

GTKPass cannot protect against:

1. **System Compromise**
   - Malware with root access
   - Keyloggers
   - Memory dumps by privileged processes

2. **Physical Access**
   - Unlocked system access
   - Cold boot attacks
   - Hardware keyloggers

3. **User Behavior**
   - Weak GPG passphrases
   - Sharing GPG keys insecurely
   - Reusing passwords

4. **Third-Party Software**
   - Compromised GPG installation
   - Malicious clipboard managers
   - Screen capture software

## Practices

### For users

1. **Use a strong GPG passphrase**, unique to the key, and let the GPG agent
   cache it rather than looking for somewhere else to store it.
2. **Protect the key material**: back it up, prefer subkeys, set expiry.
3. **Set a short clipboard timeout**, and remember what it cannot do.
4. **Keep GnuPG current.** It, not this application, is what stands between an
   attacker and your entries.

### For developers

1. **Never print or log a decrypted value**, and do not defeat the redacted
   `PasswordEntry.__repr__`.
2. **Never point development code at the real store.** Use `make devstore`.
3. **Drop plaintext when done with it**, as the detail pane does.
4. **Validate paths** that come from an entry name before they reach the file
   system.
5. **Keep dependencies few.** Every one of them can read the process memory
   that holds decrypted entries.

## Review

- Static analysis: `ruff` and `mypy`, via `make check`
- Test suite: `make test`

Both run by hand, on the way in through the pre-commit hook, and in CI on push
and pull request. There is no dependency scanning and no external audit, and the
project has not been reviewed by anyone outside it.

## Disclosure history

None. Nothing has been reported, and nothing has been released to report
against.

## Related reading

- [ARCHITECTURE.md — Handling secrets](ARCHITECTURE.md#handling-secrets), for
  the mechanisms rather than the policy
- [docs/TRUST-MODEL.md](docs/TRUST-MODEL.md), for per-machine keys, what TPM
  binding does and does not protect against, and what decryption costs
- [docs/FLATPAK.md](docs/FLATPAK.md), for every sandbox permission the Flatpak
  asks for and the ones it deliberately refuses
- [passwordstore](https://www.passwordstore.org/) and
  [GPG best practices](https://riseup.net/en/security/message-security/openpgp/best-practices),
  for the layer that actually does the encrypting
