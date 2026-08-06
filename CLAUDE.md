# Claude AI Configuration for GTKPass

This document describes how Claude AI should be used to assist with the GTKPass project development.

## Project Context

GTKPass is a modern GTK4/Libadwaita-based password manager written in Python, designed as an alternative to qtpass. It provides a native GNOME experience for managing passwords in the passwordstore (pass) format.

## Development Guidelines

### Code Style and Standards

1. **Python Code**
   - Follow PEP 8 style guidelines
   - Use type hints for all function signatures
   - Minimum Python version: 3.10
   - Use modern Python features (match/case, walrus operator, etc.)
   - Prefer dataclasses for data structures
   - Use pathlib for file operations

2. **GTK/UI Code**
   - Use GTK4 and Libadwaita
   - Write UI definitions in Blueprint (.blp) format, NOT XML
   - Follow GNOME Human Interface Guidelines (HIG)
   - Support dark mode
   - Ensure accessibility (screen readers, keyboard navigation)

3. **Security**
   - Never log or print passwords
   - Clear sensitive data from memory when done
   - Use secure random for password generation
   - Validate all user inputs
   - Handle GPG errors gracefully

### Architecture Principles

1. **Separation of Concerns**
   - Model: Password store operations, GPG, git
   - View: GTK UI components
   - Controller: Business logic, event handling

2. **Modularity**
   - Each module should have a single responsibility
   - Prefer composition over inheritance
   - Use dependency injection for testability

3. **Error Handling**
   - Use specific exception types
   - Provide user-friendly error messages
   - Log errors for debugging
   - Never crash the application

### Technology Stack

**Core Dependencies:**
- GTK4: UI framework
- Libadwaita: Modern GNOME widgets
- python-gnupg: GPG operations
- keyring: System keyring integration
- GitPython: Git operations
- pyotp: OTP generation
- qrcode: QR code generation
- pillow: Image handling
- opencv-python or zxing: QR code scanning

**Development Dependencies:**
- pytest: Testing framework
- pytest-cov: Code coverage
- mypy: Static type checking
- ruff: Linting and formatting
- black: Code formatting (if not using ruff)

### File Organization

```
gtkpass/
├── src/
│   └── gtkpass/
│       ├── __init__.py
│       ├── __main__.py          # Entry point
│       ├── app.py               # Application class
│       ├── window.py            # Main window
│       ├── models/              # Data models
│       │   ├── __init__.py
│       │   ├── password.py
│       │   ├── password_store.py
│       │   └── otp.py
│       ├── services/            # Business logic
│       │   ├── __init__.py
│       │   ├── gpg_service.py
│       │   ├── git_service.py
│       │   ├── keyring_service.py
│       │   ├── otp_service.py
│       │   └── qr_service.py
│       ├── ui/                  # UI components
│       │   ├── __init__.py
│       │   ├── password_list.py
│       │   ├── password_detail.py
│       │   ├── password_editor.py
│       │   ├── preferences.py
│       │   └── blueprints/      # Blueprint UI files
│       │       ├── window.blp
│       │       ├── password_editor.blp
│       │       └── preferences.blp
│       └── utils/               # Utilities
│           ├── __init__.py
│           ├── clipboard.py
│           ├── password_generator.py
│           └── validators.py
├── tests/
│   ├── __init__.py
│   ├── test_models/
│   ├── test_services/
│   └── test_utils/
├── data/
│   ├── icons/                   # Application icons
│   ├── gtkpass.desktop          # Desktop entry
│   └── gtkpass.metainfo.xml     # AppStream metadata
├── docs/
│   ├── user_guide.md
│   ├── developer_guide.md
│   └── api/
├── pyproject.toml               # Project metadata
├── README.md
├── REQUIREMENTS.md
├── LICENSE
└── .gitignore
```

## Claude Interaction Patterns

### When Adding New Features

1. **Understand Requirements**
   - Review REQUIREMENTS.md for relevant requirements
   - Identify affected components
   - Consider security implications

2. **Design First**
   - Propose API/interface changes
   - Consider backward compatibility
   - Discuss testing strategy

3. **Implementation**
   - Write tests first (TDD when appropriate)
   - Implement minimal changes
   - Add type hints
   - Document public APIs

4. **Review**
   - Run tests and linters
   - Check for security issues
   - Verify UI/UX changes
   - Update documentation

### When Fixing Bugs

1. **Reproduce**
   - Create minimal test case
   - Understand root cause
   - Check for similar issues

2. **Fix**
   - Make minimal changes
   - Add regression test
   - Verify fix doesn't break other features

3. **Document**
   - Add comments if logic is complex
   - Update changelog

### When Refactoring

1. **Justify**
   - Explain benefits of refactoring
   - Identify risks
   - Ensure tests exist

2. **Incremental Changes**
   - Small, focused commits
   - Keep tests passing
   - Maintain functionality

3. **Validate**
   - Run full test suite
   - Manual testing of affected features
   - Performance testing if relevant

## Testing Guidelines

### Unit Tests
- Test each function/method in isolation
- Use mocks for external dependencies (GPG, git, filesystem)
- Aim for 80%+ code coverage
- Test edge cases and error conditions

### Integration Tests
- Test interactions between components
- Use temporary directories for filesystem operations
- Mock external services (git remotes, keyring)
- Test complete workflows

### UI Tests
- Test critical user workflows
- Verify keyboard shortcuts work
- Test accessibility features
- Ensure responsive design works

### Security Tests
- Test password generation randomness
- Verify clipboard clearing
- Test GPG encryption/decryption
- Check for information leakage

## Security Considerations

### Password Handling
- Never store passwords in plain text (even in memory longer than necessary)
- Use secure memory clearing when available
- Don't log sensitive data
- Validate all password-related inputs

### GPG Operations
- Verify GPG signatures
- Handle GPG errors gracefully
- Support GPG agent
- Allow key selection

### Clipboard
- Clear clipboard after timeout
- Use secure clipboard APIs when available
- Notify user when clipboard is cleared

### Keyring Integration
- Use system keyring when available
- Fallback gracefully if unavailable
- Respect user's keyring security settings
- Clear keyring data on logout

## Code Review Checklist

When reviewing code (or asking Claude to review):

- [ ] Code follows PEP 8 and project style
- [ ] Type hints are present and correct
- [ ] Tests are included and passing
- [ ] Documentation is updated
- [ ] No security vulnerabilities introduced
- [ ] No sensitive data logged
- [ ] Error handling is appropriate
- [ ] UI follows GNOME HIG
- [ ] Accessibility is maintained
- [ ] Performance is acceptable
- [ ] No unnecessary dependencies added

## Common Patterns

### Working with Passwords

```python
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

@dataclass
class Password:
    """Represents a password entry."""
    name: str
    path: Path
    password: str
    username: Optional[str] = None
    url: Optional[str] = None
    notes: Optional[str] = None
    otp_secret: Optional[str] = None

    def clear(self) -> None:
        """Clear sensitive data from memory."""
        self.password = ""
        if self.otp_secret:
            self.otp_secret = ""
```

### GTK4 UI Component

```python
from gi.repository import Gtk, Adw

@Gtk.Template(resource_path='/org/gnome/gtkpass/ui/password_editor.ui')
class PasswordEditor(Adw.Dialog):
    """Dialog for editing password entries."""

    __gtype_name__ = 'PasswordEditor'

    password_entry = Gtk.Template.Child()
    username_entry = Gtk.Template.Child()

    def __init__(self, password: Optional[Password] = None):
        super().__init__()
        self._password = password
        if password:
            self._load_password()

    @Gtk.Template.Callback()
    def on_save_clicked(self, button: Gtk.Button) -> None:
        """Handle save button click."""
        # Implementation
        pass
```

### Service Layer

```python
from pathlib import Path
from typing import Optional, Protocol
import gnupg

class GPGService(Protocol):
    """Interface for GPG operations."""

    def encrypt(self, data: str, recipients: list[str]) -> str:
        """Encrypt data for recipients."""
        ...

    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt data."""
        ...

class GnuPGService:
    """Implementation using python-gnupg."""

    def __init__(self, gnupg_home: Optional[Path] = None):
        self.gpg = gnupg.GPG(gnupghome=str(gnupg_home) if gnupg_home else None)

    def encrypt(self, data: str, recipients: list[str]) -> str:
        encrypted = self.gpg.encrypt(data, recipients, always_trust=False)
        if not encrypted.ok:
            raise EncryptionError(encrypted.status)
        return str(encrypted)

    def decrypt(self, encrypted_data: str) -> str:
        decrypted = self.gpg.decrypt(encrypted_data)
        if not decrypted.ok:
            raise DecryptionError(decrypted.status)
        return str(decrypted)
```

## Blueprint UI Example

```blp
using Gtk 4.0;
using Adw 1;

template $PasswordEditor : Adw.Dialog {
  title: _("Edit Password");
  content-width: 400;
  content-height: 500;

  Adw.ToolbarView {
    [top]
    Adw.HeaderBar {
      [start]
      Button cancel_button {
        label: _("Cancel");
        action-name: "window.close";
      }

      [end]
      Button save_button {
        label: _("Save");
        style-class: "suggested-action";
        clicked => $on_save_clicked();
      }
    }

    content: Adw.PreferencesPage {
      Adw.PreferencesGroup {
        title: _("Password Details");

        Adw.EntryRow name_entry {
          title: _("Name");
        }

        Adw.PasswordEntryRow password_entry {
          title: _("Password");
        }

        Adw.EntryRow username_entry {
          title: _("Username");
        }

        Adw.EntryRow url_entry {
          title: _("URL");
        }
      }
    };
  }
}
```

## Questions to Ask

When working on GTKPass, Claude should ask:

1. **Before implementing**: "Should this follow the GNOME HIG pattern for [X]?"
2. **Security concerns**: "This involves sensitive data - should we add additional security measures?"
3. **Dependencies**: "This requires a new dependency - is it acceptable?"
4. **Breaking changes**: "This changes the API - how should we handle backward compatibility?"
5. **Performance**: "This operation might be slow with many passwords - should we optimize?"

## Resources

- GNOME HIG: https://developer.gnome.org/hig/
- GTK4 Documentation: https://docs.gtk.org/gtk4/
- Libadwaita Documentation: https://gnome.pages.gitlab.gnome.org/libadwaita/
- Blueprint Documentation: https://jwestman.pages.gitlab.gnome.org/blueprint-compiler/
- passwordstore: https://www.passwordstore.org/
- pass-otp: https://github.com/tadfisher/pass-otp

## Version Control

- Use conventional commits (feat:, fix:, docs:, etc.)
- Keep commits atomic and focused
- Write clear commit messages
- Reference requirements in commits (e.g., "feat: implement OTP generation (REQ-OTP-001)")

## Continuous Integration

Expected CI checks:
- Linting (ruff)
- Type checking (mypy)
- Tests (pytest with coverage)
- Security scanning
- Build test (setuptools/meson)

## Release Process

1. Update version in pyproject.toml
2. Update CHANGELOG.md
3. Run full test suite
4. Build distribution packages
5. Tag release in git
6. Push to PyPI
7. Update Flathub manifest

## Accessibility

- Support keyboard navigation for all features
- Provide screen reader labels
- Use high contrast when needed
- Follow GNOME accessibility guidelines
- Test with Orca screen reader
