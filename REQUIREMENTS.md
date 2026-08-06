> **Status: wish list, not a description of the software.**
> Written before implementation and never revised since. Much of it is not
> built, and some of it — OTP, QR codes, git integration, keyring storage — is
> not planned; see the closing section of [ARCHITECTURE.md](ARCHITECTURE.md).
> For what exists today, read [README.md](README.md) and
> [ARCHITECTURE.md](ARCHITECTURE.md).

# GTKPass Requirements Specification

## Project Overview

GTKPass is a modern GTK-based password manager designed as an alternative to qtpass. It provides a user-friendly interface for managing passwords stored in the passwordstore (pass) format, with additional features for OTP, QR codes, and lifecycle management.

## Core Requirements

### 1. Password Management

#### 1.1 Password Storage
- **REQ-PM-001**: Support standard passwordstore format (compatible with `pass`)
- **REQ-PM-002**: Store passwords encrypted with GPG
- **REQ-PM-003**: Support hierarchical organization of passwords (folder structure)
- **REQ-PM-004**: Display password list in a tree view
- **REQ-PM-005**: Support search and filtering of passwords
- **REQ-PM-006**: Copy passwords to clipboard with auto-clear timeout
- **REQ-PM-007**: Show/hide password functionality
- **REQ-PM-008**: Support password metadata (username, URL, notes)

#### 1.2 Password Operations
- **REQ-PM-009**: View existing passwords
- **REQ-PM-010**: Edit existing passwords
- **REQ-PM-011**: Delete passwords with confirmation
- **REQ-PM-012**: Move/rename passwords
- **REQ-PM-013**: Duplicate passwords
- **REQ-PM-014**: Copy username to clipboard
- **REQ-PM-015**: Copy URL to clipboard

### 2. Security and Safety

#### 2.1 Encryption
- **REQ-SEC-001**: Use GPG for encryption/decryption
- **REQ-SEC-002**: Support multiple GPG keys for team sharing
- **REQ-SEC-003**: Verify GPG signatures on password retrieval
- **REQ-SEC-004**: Support GPG key selection for new passwords
- **REQ-SEC-005**: Handle GPG passphrase caching securely

#### 2.2 Access Control
- **REQ-SEC-006**: Integrate with system keyring for GPG passphrase storage
- **REQ-SEC-007**: Auto-lock after configurable timeout
- **REQ-SEC-008**: Clear clipboard after configurable timeout (default 45 seconds)
- **REQ-SEC-009**: Prevent screenshots of password fields (platform-dependent)
- **REQ-SEC-010**: Support session locking

#### 2.3 Audit and Logging
- **REQ-SEC-011**: Log password access events (optional)
- **REQ-SEC-012**: Track password age
- **REQ-SEC-013**: Warn about weak passwords
- **REQ-SEC-014**: Warn about reused passwords
- **REQ-SEC-015**: Support password history via git integration

### 3. Secret Creation

#### 3.1 Password Generation
- **REQ-GEN-001**: Generate secure random passwords
- **REQ-GEN-002**: Configurable password length (default 24 characters)
- **REQ-GEN-003**: Configurable character sets (uppercase, lowercase, numbers, symbols)
- **REQ-GEN-004**: Exclude ambiguous characters (optional)
- **REQ-GEN-005**: Generate pronounceable passwords (optional)
- **REQ-GEN-006**: Generate passphrases using word lists
- **REQ-GEN-007**: Show password strength indicator
- **REQ-GEN-008**: Preview generated password before saving

#### 3.2 Password Creation Workflow
- **REQ-GEN-009**: Create new password entry
- **REQ-GEN-010**: Specify name/path for new password
- **REQ-GEN-011**: Add metadata (username, URL, notes) during creation
- **REQ-GEN-012**: Choose to generate or manually enter password
- **REQ-GEN-013**: Validate password entry before saving
- **REQ-GEN-014**: Commit to git repository (if enabled)

### 4. Keyring Integration

#### 4.1 System Keyring
- **REQ-KEY-001**: Store GPG passphrase in system keyring (GNOME Keyring, KWallet, etc.)
- **REQ-KEY-002**: Support Secret Service API (freedesktop.org)
- **REQ-KEY-003**: Auto-unlock keyring on application start (if system permits)
- **REQ-KEY-004**: Securely clear keyring data on logout
- **REQ-KEY-005**: Support keyring selection for multiple password stores

#### 4.2 Integration Options
- **REQ-KEY-006**: Use python-keyring library for cross-platform support
- **REQ-KEY-007**: Fallback to password prompt if keyring unavailable
- **REQ-KEY-008**: Option to disable keyring integration
- **REQ-KEY-009**: Respect system keyring security policies

### 5. Passwordstore Integration

#### 5.1 CLI Integration
- **REQ-PS-001**: Execute `pass` CLI commands when available
- **REQ-PS-002**: Parse `pass` output for password retrieval
- **REQ-PS-003**: Use `pass` for password generation (optional)
- **REQ-PS-004**: Support `pass` extensions (pass-otp, etc.)
- **REQ-PS-005**: Detect and use existing pass configuration

#### 5.2 Native Implementation
- **REQ-PS-006**: Implement passwordstore operations natively in Python
- **REQ-PS-007**: Support reading .password-store directory
- **REQ-PS-008**: GPG encryption/decryption via python-gnupg
- **REQ-PS-009**: Native git operations via GitPython
- **REQ-PS-010**: Automatically detect passwordstore location (~/.password-store)
- **REQ-PS-011**: Support custom passwordstore location

#### 5.3 Git Integration
- **REQ-PS-012**: Auto-commit password changes
- **REQ-PS-013**: Push to remote repository (optional)
- **REQ-PS-014**: Pull from remote repository
- **REQ-PS-015**: Show git history for passwords
- **REQ-PS-016**: Sync conflict resolution
- **REQ-PS-017**: Support multiple git remotes

### 6. Modern GTK UI

#### 6.1 GTK4 and Libadwaita
- **REQ-UI-001**: Use GTK4 as the UI framework
- **REQ-UI-002**: Use Libadwaita for modern GNOME design patterns
- **REQ-UI-003**: Use Blueprint UI files (modern .blp format) instead of legacy XML Builder
- **REQ-UI-004**: Support dark mode
- **REQ-UI-005**: Support GNOME HIG (Human Interface Guidelines)
- **REQ-UI-006**: Responsive design for different window sizes

#### 6.2 UI Components
- **REQ-UI-007**: Header bar with primary actions
- **REQ-UI-008**: Sidebar with password tree view
- **REQ-UI-009**: Detail view for selected password
- **REQ-UI-010**: Search bar with filter options
- **REQ-UI-011**: Toast notifications for actions
- **REQ-UI-012**: Popovers for quick actions
- **REQ-UI-013**: Dialogs for password creation/editing
- **REQ-UI-014**: Preferences window

#### 6.3 User Experience
- **REQ-UI-015**: Keyboard shortcuts for common actions
- **REQ-UI-016**: Drag and drop for organizing passwords
- **REQ-UI-017**: Context menus for password items
- **REQ-UI-018**: Quick copy buttons (password, username, URL)
- **REQ-UI-019**: Visual feedback for copy operations
- **REQ-UI-020**: Undo/redo support for operations

### 7. OTP Support

#### 7.1 TOTP/HOTP
- **REQ-OTP-001**: Generate Time-based One-Time Passwords (TOTP)
- **REQ-OTP-002**: Generate HMAC-based One-Time Passwords (HOTP)
- **REQ-OTP-003**: Support otpauth:// URI format
- **REQ-OTP-004**: Store OTP secrets in passwordstore format
- **REQ-OTP-005**: Display current OTP code with countdown timer
- **REQ-OTP-006**: Copy OTP code to clipboard
- **REQ-OTP-007**: Support 6 and 8 digit OTP codes
- **REQ-OTP-008**: Support custom time steps (default 30 seconds)

#### 7.2 OTP Management
- **REQ-OTP-009**: Add OTP to existing password entry
- **REQ-OTP-010**: Remove OTP from password entry
- **REQ-OTP-011**: Edit OTP configuration
- **REQ-OTP-012**: Import OTP from QR code
- **REQ-OTP-013**: Export OTP as QR code
- **REQ-OTP-014**: Compatible with pass-otp format

### 8. QR Code Support

#### 8.1 QR Code Generation
- **REQ-QR-001**: Generate QR codes for passwords
- **REQ-QR-002**: Generate QR codes for OTP secrets
- **REQ-QR-003**: Generate QR codes for Wi-Fi credentials
- **REQ-QR-004**: Configurable QR code size
- **REQ-QR-005**: Display QR code in dialog window
- **REQ-QR-006**: Export QR code as image file (PNG, SVG)

#### 8.2 QR Code Scanning
- **REQ-QR-007**: Scan QR codes from webcam
- **REQ-QR-008**: Import QR code from image file
- **REQ-QR-009**: Parse otpauth:// URIs from QR codes
- **REQ-QR-010**: Parse Wi-Fi credentials from QR codes
- **REQ-QR-011**: Handle QR code scan errors gracefully

### 9. Lifecycle Management

#### 9.1 Password Health
- **REQ-LIFE-001**: Track password creation date
- **REQ-LIFE-002**: Track password last modified date
- **REQ-LIFE-003**: Calculate password age
- **REQ-LIFE-004**: Warn when passwords exceed age threshold (e.g., 90 days)
- **REQ-LIFE-005**: Identify weak passwords (strength analysis)
- **REQ-LIFE-006**: Identify duplicate passwords
- **REQ-LIFE-007**: Identify reused passwords across sites

#### 9.2 Password Rotation
- **REQ-LIFE-008**: Schedule password rotation reminders
- **REQ-LIFE-009**: Track password rotation history
- **REQ-LIFE-010**: Batch password update workflow
- **REQ-LIFE-011**: Export password rotation report

#### 9.3 Maintenance Tools
- **REQ-LIFE-012**: Check GPG key expiration
- **REQ-LIFE-013**: Re-encrypt all passwords with new key
- **REQ-LIFE-014**: Backup password store
- **REQ-LIFE-015**: Restore from backup
- **REQ-LIFE-016**: Verify password store integrity
- **REQ-LIFE-017**: Clean up orphaned files
- **REQ-LIFE-018**: Optimize git repository (gc, prune)

## Non-Functional Requirements

### Performance
- **REQ-PERF-001**: Application startup under 2 seconds
- **REQ-PERF-002**: Password search results under 100ms for 1000+ passwords
- **REQ-PERF-003**: Lazy loading for large password trees
- **REQ-PERF-004**: Efficient clipboard operations

### Compatibility
- **REQ-COMPAT-001**: Linux (primary target)
- **REQ-COMPAT-002**: Support GNOME desktop environment
- **REQ-COMPAT-003**: Compatible with existing passwordstore repositories
- **REQ-COMPAT-004**: Python 3.10+ required
- **REQ-COMPAT-005**: GTK 4.10+ required
- **REQ-COMPAT-006**: Libadwaita 1.4+ required

### Documentation
- **REQ-DOC-001**: User manual
- **REQ-DOC-002**: Developer documentation
- **REQ-DOC-003**: API documentation
- **REQ-DOC-004**: Installation guide
- **REQ-DOC-005**: Contributing guidelines

### Testing
- **REQ-TEST-001**: Unit tests for core functions (80%+ coverage)
- **REQ-TEST-002**: Integration tests for passwordstore operations
- **REQ-TEST-003**: UI tests for critical workflows
- **REQ-TEST-004**: Security audit for cryptographic operations

## Out of Scope

The following features are explicitly out of scope for the initial release:
- Browser extension integration
- Mobile applications
- Cloud synchronization beyond git
- Plugin system for third-party extensions
- Multi-user/team features beyond GPG key sharing
- Built-in password sharing (use GPG recipient management)

## Future Considerations

Features to consider for future releases:
- Password import from other password managers (1Password, LastPass, Bitwarden)
- Password export in various formats
- Advanced password policies
- Custom password templates
- Password breach checking (Have I Been Pwned integration)
- Biometric authentication support
- Wayland-specific security features
