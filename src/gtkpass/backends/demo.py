"""Demo backend for GTKPass.

Provides a read-only backend with sample password data loaded from JSON.
Useful for demos, testing UI, and screenshots.
"""

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from . import (
    BackendError,
    BackendMetadata,
    BackendSettings,
    PasswordBackend,
    PasswordEntry,
    PasswordMetadata,
)


@dataclass
class DemoBackendSettings(BackendSettings):
    """Settings for demo backend.

    Attributes:
        custom_data_path: Optional path to custom demo.json file (None = use default)
    """

    custom_data_path: Path | None = None


class DemoBackend(PasswordBackend):
    """Demo backend with hardcoded sample data.

    This backend loads sample password data from a JSON file and provides
    read-only access. All mutation operations (add, edit, delete, etc.) will
    raise BackendError.

    The demo data is loaded from package data using importlib.resources,
    with an optional override path for custom demo data.
    """

    metadata = BackendMetadata(
        id="demo",
        name="Demo",
        icon="starred-symbolic",
        description="Read-only demo data for testing",
    )

    def __init__(self, demo_data: list[dict]):
        """Initialize demo backend with data.

        Args:
            demo_data: List of password entry dictionaries
        """
        self._data = demo_data
        self._entries_cache: dict[str, PasswordEntry] = {}

        # Build password entries cache
        for item in demo_data:
            entry = PasswordEntry(
                name=item["name"],
                path=Path(f"demo://{item['name']}"),
                content=None,  # Not loaded by default
            )
            self._entries_cache[item["name"]] = entry

    @staticmethod
    def _load_default_data() -> list[dict]:
        """Load default demo data from package resources."""
        try:
            data_file = files("gtkpass.backends") / "data" / "demo.json"
            with data_file.open("r") as f:
                return json.load(f)
        except Exception:
            # Fallback to minimal data
            return [
                {
                    "name": "example/email",
                    "password": "demo_password_123",
                    "username": "user@example.com",
                    "url": "https://mail.example.com",
                    "notes": "Demo email account",
                }
            ]

    @classmethod
    def is_available(cls) -> bool:
        """Check if demo backend is available.

        Returns:
            Always True - demo backend is always available
        """
        return True

    @classmethod
    def create(cls, settings: DemoBackendSettings | None = None) -> "DemoBackend":
        """Create and initialize a backend instance.

        Args:
            settings: Demo backend settings (uses defaults if None)

        Returns:
            Initialized backend instance

        Raises:
            BackendError: If initialization fails
        """
        if not cls.is_available():
            raise BackendError(f"{cls.metadata.name} backend is not available")

        if settings is None:
            settings = DemoBackendSettings()

        # Load demo data
        if settings.custom_data_path and settings.custom_data_path.exists():
            demo_file = settings.custom_data_path / "demo.json"
            if demo_file.exists():
                with open(demo_file) as f:
                    demo_data = json.load(f)
            else:
                demo_data = cls._load_default_data()
        else:
            demo_data = cls._load_default_data()

        return cls(demo_data=demo_data)

    def list_passwords(self, prefix: str = "") -> list[PasswordMetadata]:
        """List all passwords, optionally filtered by prefix.

        Args:
            prefix: Optional prefix to filter results

        Returns:
            List of password metadata (content not loaded)
        """
        results = []
        for name, entry in self._entries_cache.items():
            if not prefix or name.startswith(prefix):
                metadata = PasswordMetadata(
                    name=name,
                    path=entry.path,
                    modified=0.0,  # Demo data doesn't have timestamps
                )
                results.append(metadata)

        return sorted(results, key=lambda x: x.name)

    def get_password(self, name: str) -> PasswordEntry:
        """Get a specific password entry (decrypted).

        Args:
            name: Name of the password

        Returns:
            Password entry with content loaded

        Raises:
            FileNotFoundError: If password doesn't exist
        """
        if name not in self._entries_cache:
            raise FileNotFoundError(f"Password '{name}' not found in demo data")

        # Find the original data
        for item in self._data:
            if item["name"] == name:
                return PasswordEntry(
                    name=name,
                    path=Path(f"demo://{name}"),
                    content=item["content"],
                )

        raise FileNotFoundError(f"Password '{name}' not found in demo data")

    def add_password(self, name: str, content: str, commit: bool = True) -> None:
        """Add a new password entry.

        Raises:
            BackendError: Demo backend is read-only
        """
        raise BackendError("Demo backend is read-only")

    def edit_password(self, name: str, content: str, commit: bool = True) -> None:
        """Edit an existing password entry.

        Raises:
            BackendError: Demo backend is read-only
        """
        raise BackendError("Demo backend is read-only")

    def delete_password(self, name: str, commit: bool = True) -> None:
        """Delete a password entry.

        Raises:
            BackendError: Demo backend is read-only
        """
        raise BackendError("Demo backend is read-only")

    def move_password(self, old_name: str, new_name: str, commit: bool = True) -> None:
        """Move/rename a password entry.

        Raises:
            BackendError: Demo backend is read-only
        """
        raise BackendError("Demo backend is read-only")

    def copy_password(self, source: str, dest: str, commit: bool = True) -> None:
        """Copy a password entry.

        Raises:
            BackendError: Demo backend is read-only
        """
        raise BackendError("Demo backend is read-only")

    def search(self, query: str) -> list[PasswordMetadata]:
        """Search for passwords matching query.

        Args:
            query: Search query (case-insensitive)

        Returns:
            List of matching password metadata entries
        """
        query_lower = query.lower()
        results = []

        for name, entry in self._entries_cache.items():
            if query_lower in name.lower():
                metadata = PasswordMetadata(
                    name=name,
                    path=entry.path,
                    modified=0.0,
                )
                results.append(metadata)

        return sorted(results, key=lambda x: x.name)
