# GTKPass Architecture Overview

## Introduction

This document describes the software architecture of GTKPass, a modern GTK4-based password manager for Linux/GNOME.

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                   GTK4 UI Layer                      │
│  (Libadwaita Widgets, Blueprint UI Definitions)     │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│              Application Layer                       │
│  (Controllers, View Models, Event Handlers)          │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│               Service Layer                          │
│  (GPG, Git, OTP, QR, Keyring Services)              │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│              Domain Model Layer                      │
│  (Password, PasswordStore, OTPToken Models)          │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│          External Systems & Storage                  │
│  (Filesystem, GPG, Git, System Keyring)             │
└─────────────────────────────────────────────────────┘
```

## Component Architecture

### 1. UI Layer Components

#### 1.1 Main Application Window
- **Purpose**: Primary application container
- **Responsibilities**:
  - Host sidebar and content views
  - Manage global shortcuts
  - Handle application state
- **Technology**: Adw.ApplicationWindow with Blueprint definition

#### 1.2 Password List (Sidebar)
- **Purpose**: Display password hierarchy
- **Responsibilities**:
  - Show password tree structure
  - Handle search/filter
  - Support selection
- **Technology**: Gtk.TreeView or Gtk.ListView with custom model

#### 1.3 Password Detail View
- **Purpose**: Display selected password details
- **Responsibilities**:
  - Show password information
  - Provide quick actions (copy, edit)
  - Display OTP if available
- **Technology**: Custom Adw widget with Blueprint definition

#### 1.4 Password Editor Dialog
- **Purpose**: Create/edit password entries
- **Responsibilities**:
  - Form for password details
  - Password generation
  - Validation
- **Technology**: Adw.Dialog with Blueprint definition

#### 1.5 Preferences Window
- **Purpose**: Application settings
- **Responsibilities**:
  - Configure application behavior
  - Set security options
  - Manage password store location
- **Technology**: Adw.PreferencesWindow

### 2. Application Layer Components

#### 2.1 Application Class
```python
class GTKPassApp(Adw.Application):
    """Main application class."""
    - Initialize services
    - Setup signal handlers
    - Manage application lifecycle
```

#### 2.2 Controllers
- **PasswordListController**: Handle password list interactions
- **PasswordDetailController**: Manage detail view updates
- **EditorController**: Handle password editing logic

### 3. Service Layer Components

#### 3.1 GPG Service
```python
class GPGService:
    """Handle GPG encryption/decryption."""
    - encrypt(data: str, recipients: list[str]) -> str
    - decrypt(data: str) -> str
    - list_keys() -> list[GPGKey]
    - verify_signature(data: str) -> bool
```

#### 3.2 PasswordStore Service
```python
class PasswordStoreService:
    """Manage passwordstore operations."""
    - list_passwords() -> list[PasswordEntry]
    - get_password(path: Path) -> Password
    - save_password(password: Password) -> None
    - delete_password(path: Path) -> None
    - move_password(old_path: Path, new_path: Path) -> None
```

#### 3.3 Git Service
```python
class GitService:
    """Handle git operations."""
    - commit(message: str, files: list[Path]) -> None
    - push() -> None
    - pull() -> None
    - get_history(path: Path) -> list[GitCommit]
    - sync() -> None
```

#### 3.4 Keyring Service
```python
class KeyringService:
    """Integrate with system keyring."""
    - store_passphrase(key: str, passphrase: str) -> None
    - get_passphrase(key: str) -> Optional[str]
    - delete_passphrase(key: str) -> None
```

#### 3.5 OTP Service
```python
class OTPService:
    """Generate and manage OTP tokens."""
    - generate_totp(secret: str) -> str
    - generate_hotp(secret: str, counter: int) -> str
    - parse_otpauth_uri(uri: str) -> OTPConfig
    - create_otpauth_uri(config: OTPConfig) -> str
```

#### 3.6 QR Service
```python
class QRService:
    """Handle QR code generation and scanning."""
    - generate_qr(data: str) -> Image
    - scan_qr_from_camera() -> str
    - scan_qr_from_file(path: Path) -> str
```

### 4. Domain Model Layer

#### 4.1 Password Model
```python
@dataclass
class Password:
    """Password entry model."""
    name: str
    path: Path
    password: str
    username: Optional[str]
    url: Optional[str]
    notes: Optional[str]
    otp_secret: Optional[str]
    created_at: datetime
    modified_at: datetime

    def to_passwordstore_format() -> str
    def from_passwordstore_format(content: str) -> 'Password'
    def clear_sensitive_data() -> None
```

#### 4.2 PasswordStore Model
```python
class PasswordStore:
    """Password store repository."""
    store_path: Path
    gpg_service: GPGService
    git_service: Optional[GitService]

    def initialize() -> None
    def get_password(path: Path) -> Password
    def list_passwords(prefix: Optional[Path]) -> list[Path]
    def search(query: str) -> list[Path]
```

#### 4.3 OTPToken Model
```python
@dataclass
class OTPToken:
    """OTP token model."""
    type: Literal['totp', 'hotp']
    secret: str
    digits: int = 6
    period: int = 30  # for TOTP
    counter: int = 0  # for HOTP
    algorithm: str = 'SHA1'
    issuer: Optional[str] = None
    account: Optional[str] = None
```

### 5. Utility Components

#### 5.1 Password Generator
```python
class PasswordGenerator:
    """Generate secure passwords."""
    - generate_random(length: int, charset: str) -> str
    - generate_passphrase(word_count: int) -> str
    - calculate_strength(password: str) -> float
```

#### 5.2 Clipboard Manager
```python
class ClipboardManager:
    """Manage clipboard operations."""
    - copy_text(text: str, timeout: int) -> None
    - clear() -> None
    - start_clear_timer(timeout: int) -> None
```

#### 5.3 Validators
```python
class PasswordValidator:
    """Validate password entries."""
    - validate_name(name: str) -> ValidationResult
    - validate_password(password: str) -> ValidationResult
    - check_strength(password: str) -> StrengthResult
```

## Data Flow

### Password Retrieval Flow

```
User Clicks Password
        │
        ▼
PasswordListController.on_password_selected()
        │
        ▼
PasswordStoreService.get_password(path)
        │
        ▼
GPGService.decrypt(encrypted_content)
        │
        ▼
Password.from_passwordstore_format(content)
        │
        ▼
PasswordDetailView.display(password)
        │
        ▼
ClipboardManager.copy_text(password.password, timeout=45)
```

### Password Creation Flow

```
User Clicks "New Password"
        │
        ▼
PasswordEditorDialog.show()
        │
        ▼
User Fills Form / Generates Password
        │
        ▼
EditorController.on_save()
        │
        ▼
PasswordValidator.validate(password_data)
        │
        ▼
Password.to_passwordstore_format()
        │
        ▼
GPGService.encrypt(content, recipients)
        │
        ▼
PasswordStoreService.save_password(password)
        │
        ▼
GitService.commit("Add password", [path])
        │
        ▼
PasswordListView.refresh()
```

### OTP Generation Flow

```
User Views Password with OTP
        │
        ▼
PasswordDetailView.display_otp()
        │
        ▼
OTPService.generate_totp(otp_secret)
        │
        ▼
Display OTP Code + Countdown Timer
        │
        ▼
Timer Expires (30 seconds)
        │
        ▼
OTPService.generate_totp(otp_secret)  [Refresh]
```

## Storage Format

### Password File Format

Standard passwordstore format:
```
<password>
<optional metadata lines>
```

Extended format with metadata:
```
<password>
username: <username>
url: <url>
otp: <otpauth_uri>
notes: <multi-line notes>
```

### Directory Structure

```
~/.password-store/
├── .gpg-id                 # GPG recipient IDs
├── .git/                   # Git repository
├── work/
│   ├── email.gpg
│   └── vpn.gpg
├── personal/
│   ├── bank.gpg
│   └── social/
│       ├── twitter.gpg
│       └── facebook.gpg
└── .extensions/
    └── pass-otp/           # OTP extension data
```

## Security Architecture

### Security Layers

1. **Storage Security**
   - GPG encryption at rest
   - Filesystem permissions (700 for directories, 600 for files)
   - Git for versioning and sync

2. **Runtime Security**
   - Keyring integration for GPG passphrase
   - Memory clearing for sensitive data
   - Clipboard auto-clear timer
   - Session locking

3. **UI Security**
   - Password masking by default
   - Secure input fields (no autocomplete)
   - Screenshot prevention (when supported)
   - Visual feedback for security operations

### Threat Model

**Threats Addressed:**
- Unauthorized access to password files (mitigated by GPG encryption)
- Memory dumps (mitigated by clearing sensitive data)
- Clipboard sniffing (mitigated by auto-clear timer)
- Keyloggers (partial mitigation via secure entry)

**Threats Not Addressed:**
- Malware on the system (requires OS-level security)
- Physical access to unlocked system
- Compromised GPG keys

## Concurrency and Threading

### Main Thread (GTK)
- All UI operations
- Event handling
- Model updates

### Background Operations
- GPG encryption/decryption (can be slow)
- Git operations (network latency)
- QR code scanning (camera processing)

**Threading Strategy:**
```python
# Use GLib.idle_add for UI updates from background threads
def on_decrypt_complete(result):
    GLib.idle_add(update_ui, result)

# Use threading or asyncio for background operations
executor = ThreadPoolExecutor(max_workers=2)
future = executor.submit(gpg_service.decrypt, data)
```

## Configuration Management

### Application Settings

Stored in GSettings (XDG_CONFIG_HOME/gtkpass/):
- Password store location
- Clipboard timeout
- Auto-lock timeout
- Git sync settings
- UI preferences (dark mode, window size)

### Password Store Configuration

Standard passwordstore format (~/.password-store/):
- `.gpg-id`: GPG recipient IDs
- `.git/config`: Git configuration
- `.extensions/`: Extension configurations

## Error Handling Strategy

### Error Categories

1. **User Errors**
   - Invalid input
   - Missing required fields
   - Show user-friendly dialog

2. **System Errors**
   - GPG not available
   - Git operation failed
   - Show error with suggested action

3. **Security Errors**
   - Decryption failed
   - Invalid signature
   - Show error and log (without sensitive data)

4. **Programming Errors**
   - Assertions
   - Should not happen in production
   - Log and attempt graceful degradation

### Error Recovery

```python
try:
    password = store.get_password(path)
except DecryptionError as e:
    # User error: wrong passphrase
    show_error_dialog("Failed to decrypt password. Check your GPG passphrase.")
except FileNotFoundError:
    # System error: file missing
    show_error_dialog("Password file not found. It may have been deleted.")
    refresh_password_list()
except Exception as e:
    # Unexpected error
    logger.error(f"Unexpected error: {e}")
    show_error_dialog("An unexpected error occurred. Please report this issue.")
```

## Testing Strategy

### Unit Tests
- Test each service independently
- Mock external dependencies
- Test error conditions

### Integration Tests
- Test service interactions
- Use temporary directories
- Mock external services (git remote, keyring)

### UI Tests
- Test user workflows
- Verify keyboard shortcuts
- Test accessibility

### Security Tests
- Test encryption/decryption
- Verify clipboard clearing
- Test session locking

## Performance Considerations

### Optimization Strategies

1. **Lazy Loading**
   - Load password list on demand
   - Decrypt passwords only when viewed

2. **Caching**
   - Cache decrypted passwords (with timeout)
   - Cache password list
   - Invalidate on changes

3. **Asynchronous Operations**
   - Background git operations
   - Parallel GPG operations for multiple passwords

4. **Efficient UI Updates**
   - Update only changed items
   - Use incremental search
   - Virtual scrolling for large lists

## Extensibility

### Plugin System (Future)

```python
class PasswordStorePlugin(Protocol):
    """Plugin interface for extending functionality."""

    def on_password_save(password: Password) -> None: ...
    def on_password_load(password: Password) -> Password: ...
    def get_menu_items() -> list[MenuItem]: ...
```

### Extension Points

1. **Custom Password Generators**
2. **Import/Export Formats**
3. **Additional OTP Types**
4. **Custom UI Themes**
5. **Additional Security Checks**

## Deployment Architecture

### Distribution Methods

1. **PyPI Package**
   ```bash
   pip install gtkpass
   ```

2. **Flatpak** (Preferred for Linux)
   ```bash
   flatpak install flathub org.gnome.GTKPass
   ```

3. **Distribution Packages**
   - Debian/Ubuntu: .deb
   - Fedora/RHEL: .rpm
   - Arch: AUR package

### Dependencies

**Required:**
- Python 3.10+
- GTK4 4.10+
- Libadwaita 1.4+
- GnuPG 2.x

**Optional:**
- git (for version control)
- pass (for CLI compatibility)
- webcam (for QR scanning)

## Migration and Compatibility

### Compatibility with Existing Tools

- **pass CLI**: Full compatibility with standard format
- **qtpass**: Can use same password store
- **pass-otp**: Compatible OTP format
- **Android Password Store**: Same git repository

### Migration from Other Password Managers

Future support for importing from:
- KeePass/KeePassXC
- 1Password
- LastPass
- Bitwarden

## Monitoring and Logging

### Logging Levels

- **DEBUG**: Detailed diagnostic information
- **INFO**: General application flow
- **WARNING**: Unexpected but handled situations
- **ERROR**: Error conditions
- **CRITICAL**: Application cannot continue

### Log Format

```python
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
```

### What to Log

- Application startup/shutdown
- Password store operations (without sensitive data)
- GPG/Git errors
- Security events (failed decryption, etc.)

### What NOT to Log

- Passwords (plain or encrypted)
- GPG passphrases
- OTP secrets
- Any personally identifiable information

## Future Architecture Considerations

1. **Wayland Protocol Extensions**
   - Secure clipboard protocols
   - Screenshot prevention

2. **Hardware Security**
   - YubiKey integration
   - TPM integration

3. **Cloud Sync**
   - E2E encrypted sync service
   - Conflict resolution

4. **Mobile Apps**
   - Shared backend code
   - Platform-specific UI

5. **Browser Extension**
   - Native messaging protocol
   - Secure password filling
