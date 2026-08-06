> **Status: aspirational.** Written before implementation. Answers here
> describe the planned application, and many of the features they promise do
> not exist. See [README.md](README.md) for what actually works.

# GTKPass Frequently Asked Questions (FAQ)

## General Questions

### What is GTKPass?

GTKPass is a modern password manager for GNOME/Linux that provides a native GTK4 interface for managing passwords stored in the passwordstore (pass) format. It's designed as an alternative to qtpass with enhanced features like built-in OTP support, QR code scanning, and modern GNOME UI.

### Is GTKPass ready to use?

Not yet. GTKPass is currently in the planning and documentation phase. Development will begin soon, with a target first release in approximately 5-6 months. See [ROADMAP.md](ROADMAP.md) for the development timeline.

### How is GTKPass different from qtpass?

GTKPass is specifically designed for GNOME users and offers:
- Native GTK4/Libadwaita interface
- Built-in OTP support (no plugins needed)
- QR code scanning and generation
- Modern GNOME design
- Advanced password lifecycle management
- Better system keyring integration

See [COMPARISON.md](COMPARISON.md) for a detailed comparison.

### Can I use GTKPass with my existing password store?

Yes! GTKPass is fully compatible with the standard passwordstore format. If you're already using pass, qtpass, or Android Password Store, GTKPass will work with your existing passwords without any migration.

### Is GTKPass compatible with pass CLI?

Yes, GTKPass maintains full compatibility with the pass command-line tool. You can use both interchangeably.

## Security Questions

### Is GTKPass secure?

Security is a top priority. GTKPass:
- Uses GPG encryption for all passwords
- Integrates with system keyring
- Clears clipboard after timeout
- Supports session locking
- Never logs sensitive data
- Will undergo security audits

See [SECURITY.md](SECURITY.md) for detailed security information.

### How are passwords encrypted?

Passwords are encrypted using GPG (GnuPG), the same encryption used by the pass CLI tool. Each password is encrypted with your GPG key before being stored on disk.

### Where are passwords stored?

Passwords are stored in `~/.password-store/` by default (configurable). Each password is a separate GPG-encrypted file. The directory structure mirrors your password organization.

### Can I share passwords with my team?

Yes, using GPG's multi-recipient encryption. You can encrypt passwords for multiple GPG keys, allowing team members to decrypt them. This is a standard passwordstore feature.

### Does GTKPass send data to the internet?

No. GTKPass only accesses the network for:
- Git synchronization (if you configure it)
- No telemetry, analytics, or external connections

### What happens if I forget my GPG passphrase?

Unfortunately, without your GPG passphrase, you cannot decrypt your passwords. This is by design - the encryption is strong. Make sure to:
- Use a memorable passphrase
- Back up your GPG key securely
- Consider using keyring integration

## Features

### Does GTKPass support OTP (2FA)?

Yes! GTKPass has native support for:
- TOTP (Time-based One-Time Passwords)
- HOTP (HMAC-based One-Time Passwords)
- QR code scanning for easy setup
- QR code generation for sharing
- Compatible with pass-otp format

### Can I generate passwords?

Yes, GTKPass includes a password generator that can create:
- Random passwords with configurable length and characters
- Passphrases using word lists
- Strength indicators
- Custom character sets

### Does it support QR codes?

Yes, GTKPass can:
- Generate QR codes for passwords and OTP secrets
- Scan QR codes from webcam
- Import QR codes from image files
- Export QR codes for sharing

### Can I sync passwords across devices?

Yes, using git. GTKPass supports:
- Auto-commit on changes
- Push/pull to remote repositories
- Git history viewing
- Merge conflict handling
- Multiple git remotes

### Does it work with my GNOME keyring?

Yes, GTKPass integrates with the system keyring (GNOME Keyring, KWallet, etc.) to securely store your GPG passphrase so you don't have to enter it repeatedly.

## Technical Questions

### What are the system requirements?

- Linux operating system
- Python 3.10 or higher
- GTK4 4.10 or higher
- Libadwaita 1.4 or higher
- GnuPG 2.x
- Git (optional, for sync)

### Which Linux distributions are supported?

GTKPass should work on any modern Linux distribution with GTK4 and Libadwaita. Well-tested on:
- Fedora 38+
- Ubuntu 23.04+
- Arch Linux
- openSUSE Tumbleweed

### Does it work on Ubuntu/Debian?

Yes, but you may need to install GTK4 and Libadwaita from backports or newer repositories, as older releases may not have the required versions.

### Can I use it on Windows or macOS?

Not initially. GTKPass is designed for Linux/GNOME. Windows and macOS support is not planned for the first release. If you need cross-platform, consider qtpass.

### What about Flatpak?

Yes! GTKPass will be available as a Flatpak package on Flathub. This is the recommended installation method as it includes all dependencies.

### Can I install it with pip?

Yes, GTKPass will be available on PyPI:
```bash
pip install gtkpass
```

However, you'll need to install system dependencies (GTK4, Libadwaita) separately.

## Usage Questions

### How do I import passwords from another password manager?

Import functionality is planned for v1.1. Initially, you can:
- Use pass CLI to import
- Manually create password entries
- Wait for import feature in future release

### Can I organize passwords in folders?

Yes, GTKPass supports hierarchical organization. Passwords can be organized in nested folders, just like in pass and qtpass.

### How do I search for passwords?

GTKPass includes a fast search feature that:
- Searches password names and paths
- Updates results as you type
- Supports filtering
- Works with large password stores

### Can I edit passwords?

Yes, GTKPass provides a password editor where you can:
- Edit the password itself
- Update username and URL
- Add notes
- Configure OTP settings
- Change the name/location

### How does auto-lock work?

GTKPass can automatically lock after a period of inactivity. When locked:
- Password list remains visible
- Password contents are cleared from memory
- You must unlock to view passwords again
- Clipboard is cleared

## Development Questions

### How can I contribute?

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. You can:
- Report bugs
- Suggest features
- Write code
- Improve documentation
- Test releases

### What programming languages do I need to know?

- **Python**: Primary language (3.10+)
- **Blueprint**: UI definition language
- **Optional**: GTK/GNOME knowledge helpful

### Is the code open source?

Yes, GTKPass is licensed under GPL-3.0. The source code is available on GitHub.

### How is the project managed?

GTKPass is maintained by Ronny Pfannschmidt with community contributions. Development follows:
- Open development on GitHub
- Issue tracking
- Pull request reviews
- Regular releases

### Can I use AI (like Claude) to help contribute?

Yes! We have a [CLAUDE.md](CLAUDE.md) guide specifically for AI-assisted development. It includes coding standards, architecture patterns, and best practices.

## Compatibility Questions

### Is GTKPass compatible with pass-otp?

Yes, GTKPass uses a compatible OTP format. OTP secrets created with pass-otp will work in GTKPass and vice versa.

### Can I use GTKPass and qtpass together?

Yes! They both use the same password store format. You can:
- Use GTKPass on GNOME
- Use qtpass on other systems
- Switch between them freely
- Share the same git repository

### What about Android Password Store?

GTKPass is compatible with Android Password Store via git synchronization. Changes made on your phone will sync to GTKPass and vice versa.

### Does it work with password-store extensions?

GTKPass aims to be compatible with common pass extensions, particularly:
- pass-otp: Yes, native support
- pass-update: Planned
- pass-tomb: Not planned
- Custom extensions: May work, not guaranteed

## Troubleshooting

### GTKPass won't start - what should I check?

1. Verify Python version: `python --version` (need 3.10+)
2. Check GTK4 installation: `pkg-config --modversion gtk4`
3. Check Libadwaita: See [DEVELOPMENT.md](DEVELOPMENT.md)
4. Review error messages
5. Check GitHub issues

### I can't decrypt passwords

Possible causes:
- Wrong GPG passphrase
- GPG key not available
- Corrupted password file
- Incorrect GPG configuration

Try decrypting manually with `pass` CLI to isolate the issue.

### Git sync isn't working

Check:
- Git remote configured correctly
- SSH keys set up (if using SSH)
- Network connectivity
- Git credentials (HTTPS)
- Repository permissions

### Clipboard not clearing

GTKPass uses system clipboard. Some clipboard managers may interfere. Try:
- Disabling clipboard manager
- Checking GTKPass timeout settings
- Using manual clear

### The UI looks wrong

Ensure you have:
- GTK4 4.10+ installed
- Libadwaita 1.4+ installed
- Current theme supports GTK4
- Try with default GNOME theme

## Future Features

### Will there be a browser extension?

Planned for v1.1+. The browser extension will:
- Communicate with GTKPass via native messaging
- Support Chrome and Firefox
- Auto-fill login forms
- Generate passwords

### Will GTKPass support importing from KeePass/1Password/etc.?

Yes, import functionality is planned for v1.1. Initial support for:
- KeePass/KeePassXC
- 1Password
- LastPass
- Bitwarden

### Are mobile apps planned?

Mobile apps are under consideration for future versions:
- GNOME mobile (Librem 5, PinePhone)
- Android (maybe)
- iOS (unlikely)

### Will there be a cloud sync option?

Git is the primary sync mechanism. Native cloud sync is not planned, but you can use:
- GitHub/GitLab private repositories
- Self-hosted git servers
- Cloud git hosting

## Getting Help

### Where can I get help?

- **Documentation**: Start with [README.md](README.md)
- **Issues**: [GitHub Issues](https://github.com/RonnyPfannschmidt/gtkpass/issues)
- **Discussions**: [GitHub Discussions](https://github.com/RonnyPfannschmidt/gtkpass/discussions)
- **GNOME**: [GNOME Discourse](https://discourse.gnome.org/)

### How do I report a bug?

1. Check if it's already reported
2. Create a GitHub issue
3. Include:
   - System information
   - Steps to reproduce
   - Expected vs actual behavior
   - Error messages
   - Screenshots if relevant

### How do I request a feature?

1. Check existing feature requests
2. Create a GitHub issue or discussion
3. Explain the use case
4. Describe the desired behavior
5. Reference related requirements if applicable

### Where can I find the documentation?

All documentation is in the repository:
- [README.md](README.md) - Overview
- [REQUIREMENTS.md](REQUIREMENTS.md) - Feature requirements
- [ARCHITECTURE.md](ARCHITECTURE.md) - Technical design
- [ROADMAP.md](ROADMAP.md) - Development plan
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guide
- [DEVELOPMENT.md](DEVELOPMENT.md) - Developer guide
- [SECURITY.md](SECURITY.md) - Security policy

## About

### Who created GTKPass?

GTKPass is created by Ronny Pfannschmidt with community contributions.

### Why was GTKPass created?

To provide a modern, native GNOME experience for password management while maintaining compatibility with the passwordstore ecosystem.

### Is GTKPass affiliated with pass or qtpass?

No, GTKPass is an independent project. It's compatible with pass and qtpass but not officially affiliated.

### How is GTKPass funded?

GTKPass is an open-source project developed by volunteers. No commercial funding currently.

---

**Have a question not answered here?** Open a [GitHub Discussion](https://github.com/RonnyPfannschmidt/gtkpass/discussions) or check our other documentation.
