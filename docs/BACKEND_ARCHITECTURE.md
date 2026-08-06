# Backend Architecture

This document outlines the architecture for GTKPass password storage backends.

## Overview

GTKPass will support multiple backend implementations through a plugin-like architecture:

1. **Direct Backend**: Reads/writes GPG-encrypted files directly
2. **Pass Backend**: Delegates operations to the `pass` command-line tool (when running in flatpak)

This allows users to choose between:
- Native integration (direct backend) for better performance and fewer dependencies
- Compatibility with existing `pass` workflows when running as flatpak (pass backend)

**Note**: The Pass backend only works in flatpak environments using `flatpak-spawn`. For development in devcontainers, use the Direct backend with test password stores.

## Backend Interface

All backends must implement a common interface defined in `src/gtkpass/backends/base.py`:

```python
from abc import ABC, abstractmethod
from typing import List, Optional
from pathlib import Path
from dataclasses import dataclass

@dataclass
class PasswordEntry:
    """Represents a password entry."""
    name: str  # Relative path without .gpg extension
    path: Path  # Full path to the .gpg file
    content: Optional[str] = None  # Decrypted content (if loaded)

@dataclass
class PasswordMetadata:
    """Metadata about a password entry."""
    name: str
    path: Path
    modified: float  # Timestamp

class PasswordBackend(ABC):
    """Abstract base class for password storage backends."""

    @classmethod
    @abstractmethod
    def initialize(cls, password_store_dir: Path, gpg_id: Optional[str] = None) -> "PasswordBackend":
        """Initialize the backend with password store location.

        Returns an initialized backend instance.
        """
        pass

    @abstractmethod
    def list_passwords(self, prefix: str = "") -> List[PasswordMetadata]:
        """List all passwords, optionally filtered by prefix."""
        pass

    @abstractmethod
    def get_password(self, name: str) -> PasswordEntry:
        """Get a specific password entry (decrypted)."""
        pass

    @abstractmethod
    def add_password(self, name: str, content: str, commit: bool = True) -> None:
        """Add a new password entry."""
        pass

    @abstractmethod
    def edit_password(self, name: str, content: str, commit: bool = True) -> None:
        """Edit an existing password entry."""
        pass

    @abstractmethod
    def delete_password(self, name: str, commit: bool = True) -> None:
        """Delete a password entry."""
        pass

    @abstractmethod
    def move_password(self, old_name: str, new_name: str, commit: bool = True) -> None:
        """Move/rename a password entry."""
        pass

    @abstractmethod
    def copy_password(self, source: str, dest: str, commit: bool = True) -> None:
        """Copy a password entry."""
        pass

    @abstractmethod
    def search(self, query: str) -> List[PasswordMetadata]:
        """Search for passwords matching query."""
        pass
```

## Development Environment

**Devcontainer**: For development in the devcontainer:
- Use the Direct backend with test password stores (e.g., `/tmp/test-password-store`)
- Do NOT mount your real `~/.password-store` or `~/.gnupg` directories
- Create test GPG keys and test password stores for development/testing
- The devcontainer is isolated and secure for development work only

**Production**: When GTKPass is installed normally:
- Direct backend: Full access to `~/.password-store` and GPG agent
- Pass backend: Only available when running in flatpak (uses `flatpak-spawn --host pass`)

## Direct Backend

**Location**: `src/gtkpass/backends/direct.py`

The direct backend implements password storage operations directly using:
- **python-gnupg** or **pygpgme**: For GPG encryption/decryption
- **gitpython**: For git operations (optional)
- Direct filesystem operations

### Features

- Read/write GPG-encrypted files directly
- Parse `.gpg-id` files to determine which GPG key to use
- Support for git integration (commit changes)
- No external dependencies on `pass` command

### Advantages

- Faster (no subprocess overhead)
- Better error handling and feedback
- Cross-platform (works in containers, Windows with GPG installed)
- Can be used without `pass` installed

### Implementation Details

```python
class DirectBackend(PasswordBackend):
    def __init__(self):
        self.store_dir: Optional[Path] = None
        self.gpg_id: Optional[str] = None
        self.gpg = gnupg.GPG()
        self.git_enabled = False

    @classmethod
    def initialize(cls, password_store_dir: Path, gpg_id: Optional[str] = None) -> "DirectBackend":
        """Create and initialize a DirectBackend instance."""
        backend = cls()
        backend.store_dir = password_store_dir
        backend.store_dir.mkdir(parents=True, exist_ok=True)

        # Read .gpg-id file if not provided
        if gpg_id is None:
            gpg_id_file = backend.store_dir / ".gpg-id"
            if gpg_id_file.exists():
                backend.gpg_id = gpg_id_file.read_text().strip()
        else:
            backend.gpg_id = gpg_id

        # Check if git repo exists
        git_dir = backend.store_dir / ".git"
        backend.git_enabled = git_dir.exists()

        return backend

    def get_password(self, name: str) -> PasswordEntry:
        path = self.store_dir / f"{name}.gpg"
        if not path.exists():
            raise FileNotFoundError(f"Password '{name}' not found")

        # Decrypt file
        with open(path, 'rb') as f:
            decrypted = self.gpg.decrypt_file(f)

        if not decrypted.ok:
            raise RuntimeError(f"GPG decryption failed: {decrypted.stderr}")

        return PasswordEntry(
            name=name,
            path=path,
            content=str(decrypted)
        )
```

## Pass Backend

**Location**: `src/gtkpass/backends/pass_cli.py`

The pass backend delegates all operations to the `pass` command-line tool running on the host system.

### Features

- Uses `pass` command for all operations
- Can invoke `pass` on the host even from inside a container
- Supports all `pass` features and extensions
- Compatible with existing pass workflows

### Host Communication

To invoke `pass` on the host from a devcontainer:

1. **Mount host socket**: Mount the host's Docker socket or use a custom socket
2. **SSH to host**: Use SSH to execute commands on the host
3. **Host script**: Create a helper script on the host that the container can call
4. **Shared filesystem**: Mount the password store with proper permissions

**Recommended approach**: Use a mounted executable script

```python
class PassBackend(PasswordBackend):
    def __init__(self, pass_command: str = "pass"):
        self.pass_command = pass_command
        self.store_dir: Optional[Path] = None
        self._use_host_spawn = self._detect_container()

    def _detect_container(self) -> bool:
        """Detect if running in a container."""
        return (
            shutil.which("flatpak-spawn") is not None or
            os.path.exists("/.dockerenv") or
            os.path.exists("/run/.containerenv")
        )

    @classmethod
    def initialize(cls, password_store_dir: Path, gpg_id: Optional[str] = None,
                   pass_command: str = "pass") -> "PassBackend":
        """Create and initialize a PassBackend instance."""
        backend = cls(pass_command)
        backend.store_dir = password_store_dir

        # Set PASSWORD_STORE_DIR environment variable
        os.environ['PASSWORD_STORE_DIR'] = str(password_store_dir)
        if gpg_id:
            os.environ['PASSWORD_STORE_GPG_OPTS'] = f"--default-recipient {gpg_id}"

        return backend

    def _run_pass(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run pass command, using host spawn if in container."""
        if self._use_host_spawn and shutil.which("flatpak-spawn"):
            cmd = ["flatpak-spawn", "--host", self.pass_command] + args
        else:
            cmd = [self.pass_command] + args

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={**os.environ, "PASSWORD_STORE_DIR": str(self.store_dir)}
        )

    def get_password(self, name: str) -> PasswordEntry:
        # Run: pass show name
        result = self._run_pass(["show", name])

        return PasswordEntry(
            name=name,
            path=Path(os.environ['PASSWORD_STORE_DIR']) / f"{name}.gpg",
            content=result.stdout
        )
```

### Invoking Host Commands from Container

**Recommended: flatpak-spawn --host (Toolbox/Distrobox pattern)**

Toolbox and Distrobox containers use `flatpak-spawn --host` to execute commands on the host system. This is the cleanest approach:

```python
class PassBackend(PasswordBackend):
    def __init__(self, pass_command: str = "pass"):
        self.pass_command = pass_command
        self.store_dir: Optional[Path] = None
        self._use_host_spawn = self._detect_container()

    def _detect_container(self) -> bool:
        """Detect if running in a container that supports flatpak-spawn."""
        return (
            shutil.which("flatpak-spawn") is not None or
            os.path.exists("/.dockerenv") or
            os.path.exists("/run/.containerenv")
        )

    def _run_pass(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run pass command, using host if in container."""
        if self._use_host_spawn and shutil.which("flatpak-spawn"):
            # Use flatpak-spawn to run on host (toolbox/distrobox pattern)
            cmd = ["flatpak-spawn", "--host", self.pass_command] + args
        else:
            # Run locally
            cmd = [self.pass_command] + args

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={**os.environ, "PASSWORD_STORE_DIR": str(self.store_dir)}
        )
```

To enable this in the devcontainer, install `flatpak-spawn` or mount the host binary:

```dockerfile
# In .devcontainer/Dockerfile
RUN apt-get update && apt-get install -y flatpak-xdg-utils
```

Or mount from host:

```json
{
  "mounts": [
    "source=/usr/bin/flatpak-spawn,target=/usr/bin/flatpak-spawn,type=bind,readonly"
  ]
}
```

**Alternative 1: Direct Host Binary Mount**

Mount the `pass` binary from the host:

```json
{
  "mounts": [
    "source=/usr/bin/pass,target=/usr/local/bin/host-pass,type=bind,readonly"
  ]
}
```

```python
backend = PassBackend.initialize(
    password_store_dir=Path.home() / ".password-store",
    pass_command="/usr/local/bin/host-pass"
)
```

**Alternative 2: SSH to Host**

For remote development or when other methods aren't available:

```python
def _run_pass(self, args: List[str]) -> subprocess.CompletedProcess:
    if self._use_ssh:
        cmd = ["ssh", f"{self.host_user}@{self.host_ip}", "pass"] + args
    else:
        cmd = ["pass"] + args
    return subprocess.run(cmd, capture_output=True, text=True)
```

## Backend Selection

Users can select their preferred backend through:

1. **Configuration file** (`~/.config/gtkpass/config.toml`):
   ```toml
   [backend]
   type = "direct"  # or "pass"

   [backend.pass]
   command = "/usr/local/bin/host-pass"
   use_host = true
   ```

2. **Environment variable**:
   ```bash
   GTKPASS_BACKEND=pass gtkpass
   ```

3. **Application settings UI**

## Implementation Plan

### Phase 1: Direct Backend (Recommended First)
- Implement `DirectBackend` with python-gnupg
- Add git integration for commits
- Full test coverage

### Phase 2: Pass Backend
- Implement `PassBackend` with subprocess calls
- Add host communication options
- Document setup for devcontainer usage

### Phase 3: Backend Registry
- Create backend factory/registry
- Add configuration system
- UI for backend selection

## Testing Strategy

- **Unit tests**: Mock GPG and filesystem operations
- **Integration tests**: Use temporary password stores
- **Container tests**: Test host communication from devcontainer

## Dependencies

### Direct Backend
- `python-gnupg` or `pygpgme`
- `GitPython` (optional, for git operations)

### Pass Backend
- `pass` command (on host or in container)
- SSH client (optional, for host communication)

## Security Considerations

1. **GPG Agent**: Ensure GPG agent is accessible for password prompts
2. **Permissions**: Password store files should be 0600
3. **Host Access**: When using host pass, ensure secure communication
4. **Secret Handling**: Never log decrypted passwords
5. **Memory Cleanup**: Clear sensitive data from memory when done

## Future Extensions

- **OTP Backend**: Separate backend for TOTP/HOTP
- **Cloud Backends**: Support for cloud password stores
- **Custom Backends**: Plugin system for third-party backends
