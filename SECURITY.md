# Security Policy

## Supported Versions

GTKPass is currently in development. Once released, we will maintain security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability in GTKPass, please follow responsible disclosure:

### How to Report

1. **Email**: Send details to the maintainer (see GitHub profile for contact)
2. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if available)
3. **GPG**: Encrypt sensitive reports with maintainer's GPG key (if available)

### What to Expect

- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Fix Timeline**: Depends on severity
  - Critical: 1-7 days
  - High: 1-2 weeks
  - Medium: 2-4 weeks
  - Low: Next release

### Disclosure Policy

- We will work with you to understand and fix the issue
- We will credit you in the security advisory (unless you prefer anonymity)
- We will coordinate public disclosure after a fix is available
- Typical embargo period: 90 days or until fix is released

## Security Measures

What the application actually does today. Anything not listed here is not
implemented, whatever other documents in this repository may suggest.

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

Development and test code is blocked from opening the real store or the
keyring. The backends refuse `~/.password-store`, `$PASSWORD_STORE_DIR` and the
session Secret Service unless `GTKPASS_ALLOW_REAL_STORE` is set, which
`run_app.sh` does by default; the test suite clears it. This exists because a
decrypted password that reaches a terminal, a CI log or an AI assistant's
transcript cannot be un-disclosed.

The development store carries a marker file that exempts it, so the guard stays
armed during a development run rather than being switched off wholesale. The
default store location cannot be exempted this way.

Note that this is a guard against mistakes by people working on GTKPass, not a
security boundary. It is an environment variable: anything running as the user
can set it.

### Not implemented

Do not rely on any of these — they do not exist:

- Session locking or auto-lock after inactivity
- Storing the GPG passphrase in a keyring (GPG agent handles caching)
- Screenshot prevention
- Secure or locked memory allocation
- Signature verification
- Git integration of any kind, including signed commits

## Known Limitations

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

## Security Best Practices

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

## Security Audits

- Static analysis: `ruff` and `mypy`, via `make check`
- Test suite: `make test`

Both are run by hand and by the pre-commit hook. There is no CI, no dependency
scanning, and no external audit. The project has not been reviewed by anyone
outside it.

## Vulnerability Disclosure History

None yet (project in development).

Once released, disclosed vulnerabilities will be listed here with:
- CVE ID (if applicable)
- Severity rating
- Affected versions
- Fixed version
- Credit to reporter

## Security Contact

For security concerns, contact the maintainers through:
- GitHub Security Advisories (preferred)
- Email (see GitHub profile)
- GPG encrypted email for sensitive issues

## Related Security Documentation

- [REQUIREMENTS.md - Security Requirements](REQUIREMENTS.md#2-security-and-safety)
- [ARCHITECTURE.md - Handling secrets](ARCHITECTURE.md#handling-secrets)
- [passwordstore security](https://www.passwordstore.org/)
- [GPG Best Practices](https://riseup.net/en/security/message-security/openpgp/best-practices)

## Compliance

GTKPass aims to follow:
- OWASP Top 10 guidelines
- CWE/SANS Top 25
- GNOME security recommendations
- Python security best practices

## Security Roadmap

Planned security enhancements:
- [ ] Comprehensive security audit
- [ ] Penetration testing
- [ ] Hardware security key support (YubiKey)
- [ ] Biometric authentication
- [ ] Wayland security features
- [ ] TPM integration
- [ ] Memory encryption
- [ ] FIDO2/WebAuthn support

## Acknowledgments

We thank the security research community for helping keep GTKPass secure.

Security researchers who report vulnerabilities responsibly will be acknowledged in:
- Security advisories
- Release notes
- SECURITY.md (this file)

## License

This security policy is part of GTKPass and is licensed under MPL-2.0.

---

**Last Updated**: August 2026
