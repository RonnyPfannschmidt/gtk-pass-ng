"""Backend base classes and interfaces for password storage."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BackendMetadata:
    """Metadata about a backend.

    Attributes:
        id: Unique backend identifier (e.g., "demo", "secretservice")
        name: Human-readable name (e.g., "Demo", "Secret Service")
        icon: Icon name for UI (e.g., "starred-symbolic")
        description: Short description of the backend
    """

    id: str
    name: str
    icon: str
    description: str


@dataclass
class BackendSettings:
    """Base class for backend-specific settings.

    Each backend should subclass this to define its specific settings.
    All settings should have sensible defaults.
    """

    pass


@dataclass
class PasswordEntry:
    """Represents a password entry.

    Attributes:
        name: Relative path without .gpg extension (e.g., "email/work")
        path: Full path to the .gpg file
        content: Decrypted content (if loaded), first line is the password
    """

    name: str
    path: Path
    # Excluded from the generated repr: the default would print the decrypted
    # password into any log line, traceback or assertion diff that renders this
    # object. See __repr__ below.
    content: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        """Identify the entry without disclosing what it holds."""
        state = "loaded" if self.content else "empty"
        return f"PasswordEntry(name={self.name!r}, {state})"

    @property
    def password(self) -> str | None:
        """Get the password (first line of content)."""
        if self.content:
            return self.content.split("\n")[0]
        return None

    @property
    def metadata(self) -> dict[str, str]:
        """Parse metadata from content (lines after password).

        Returns:
            Dictionary of key-value pairs from lines containing ':'
        """
        if not self.content:
            return {}

        lines = self.content.split("\n")[1:]  # Skip password line
        metadata = {}

        for line in lines:
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip().lower()] = value.strip()

        return metadata

    def clear_password(self) -> None:
        """Clear decrypted password content from memory.

        This should be called when the password is no longer needed
        to minimize the time sensitive data stays in memory.
        """
        self.content = None


@dataclass
class PasswordMetadata:
    """Metadata about a password entry.

    Attributes:
        name: Relative path without .gpg extension
        path: Full path to the .gpg file
        modified: Unix timestamp of last modification
    """

    name: str
    path: Path
    modified: float


class PasswordBackend(ABC):
    """Abstract base class for password storage backends.

    All backend implementations must inherit from this class and implement
    all abstract methods.

    Backends are created using the create() class method factory, which checks
    availability and returns a fully initialized instance or None.

    Required class attribute:
        metadata: BackendMetadata instance with id, name, icon, description
    """

    # This must be defined by subclasses
    metadata: BackendMetadata

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Check if this backend is available on the system.

        Returns:
            True if backend can be used, False otherwise
        """
        pass

    @classmethod
    def create(cls, settings: BackendSettings | None = None) -> "PasswordBackend":
        """Create and initialize a backend instance.

        This factory method checks availability and creates a fully
        initialized backend instance.

        Args:
            settings: Backend-specific settings (uses defaults if None)

        Returns:
            Initialized backend instance

        Raises:
            BackendError: If backend is not available or initialization fails
        """
        if not cls.is_available():
            raise BackendError(f"{cls.metadata.name} backend is not available")

        try:
            return cls(settings=settings)
        except Exception as e:
            raise BackendError(
                f"Failed to initialize {cls.metadata.name} backend: {e}"
            ) from e

    @abstractmethod
    def list_passwords(self, prefix: str = "") -> list[PasswordMetadata]:
        """List all passwords, optionally filtered by prefix.

        This method returns only metadata (name, path, modified time) without
        decrypting password content. Use get_password() to retrieve and decrypt
        a specific password entry.

        Args:
            prefix: Optional prefix to filter results (e.g., "email/")

        Returns:
            List of password metadata entries (content not loaded)
        """
        pass

    @abstractmethod
    def get_password(self, name: str) -> PasswordEntry:
        """Get a specific password entry with on-demand decryption.

        This method retrieves and decrypts the password content. The returned
        PasswordEntry will have its content field populated. Call clear_password()
        on the entry when done to clear sensitive data from memory.

        Args:
            name: Name of the password (relative path without .gpg)

        Returns:
            Decrypted password entry with content populated

        Raises:
            FileNotFoundError: If password doesn't exist
            RuntimeError: If decryption fails
        """
        pass

    @abstractmethod
    def add_password(self, name: str, content: str, commit: bool = True) -> None:
        """Add a new password entry.

        Args:
            name: Name for the password (relative path without .gpg)
            content: Password content (password on first line, metadata after)
            commit: Whether to commit to git (if enabled)

        Raises:
            FileExistsError: If password already exists
            RuntimeError: If encryption or write fails
        """
        pass

    @abstractmethod
    def edit_password(self, name: str, content: str, commit: bool = True) -> None:
        """Edit an existing password entry.

        Args:
            name: Name of the password to edit
            content: New password content
            commit: Whether to commit to git (if enabled)

        Raises:
            FileNotFoundError: If password doesn't exist
            RuntimeError: If encryption or write fails
        """
        pass

    @abstractmethod
    def delete_password(self, name: str, commit: bool = True) -> None:
        """Delete a password entry.

        Args:
            name: Name of the password to delete
            commit: Whether to commit to git (if enabled)

        Raises:
            FileNotFoundError: If password doesn't exist
        """
        pass

    @abstractmethod
    def move_password(self, old_name: str, new_name: str, commit: bool = True) -> None:
        """Move/rename a password entry.

        Args:
            old_name: Current name of the password
            new_name: New name for the password
            commit: Whether to commit to git (if enabled)

        Raises:
            FileNotFoundError: If old password doesn't exist
            FileExistsError: If new name already exists
        """
        pass

    @abstractmethod
    def copy_password(self, source: str, dest: str, commit: bool = True) -> None:
        """Copy a password entry.

        Args:
            source: Name of the password to copy
            dest: Name for the copy
            commit: Whether to commit to git (if enabled)

        Raises:
            FileNotFoundError: If source doesn't exist
            FileExistsError: If destination already exists
        """
        pass

    @abstractmethod
    def search(self, query: str) -> list[PasswordMetadata]:
        """Search for passwords matching query.

        Args:
            query: Search query (case-insensitive substring match)

        Returns:
            List of matching password metadata entries
        """
        pass


class BackendError(Exception):
    """Base exception for backend errors."""

    pass


class GPGError(BackendError):
    """Exception for GPG-related errors."""

    pass


class GitError(BackendError):
    """Exception for git-related errors."""

    pass
