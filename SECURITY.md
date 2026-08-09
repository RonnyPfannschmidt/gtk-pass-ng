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

[advisories]: https://github.com/RonnyPfannschmidt/gtkpass/security/advisories

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
session keyring over D-Bus.

### Handling decrypted data

- Entries are decrypted only when opened, one at a time.
- The plaintext is dropped when the detail pane moves on to another entry.
- `PasswordEntry` excludes its content from its `repr`, which is redacted by
  hand. The generated dataclass repr would otherwise have put plaintext into
  every log line, traceback and test assertion diff that rendered an entry.
- Nothing logs a decrypted value.

Python cannot guarantee that a secret is gone from memory: strings are
immutable and the garbage collector may keep copies. Dropping references
reduces exposure; it does not eliminate it.

### Clipboard

Copying a field puts it on the clipboard and clears it again after a
configurable delay. Treat this as damage limitation, not a guarantee: a
clipboard manager may already have taken a copy, and a Wayland compositor may
refuse a clear requested by an application that is not focused.

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
- Signature verification, of entries or of anything else
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
