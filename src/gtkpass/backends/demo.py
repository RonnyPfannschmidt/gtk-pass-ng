"""Demo backend for GTKPass.

Provides a read-only backend with sample password data loaded from JSON.
Useful for demos, testing UI, and screenshots.
"""

import json
import logging
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

logger = logging.getLogger(__name__)


@dataclass
class DemoBackendSettings(BackendSettings):
    """Settings for demo backend.

    Attributes:
        custom_data_path: Optional path to a demo.json (or to a directory
            holding one). None uses the entries packaged with the application.
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

    #: Every write raises, so nothing may offer one for this backend.
    writable = False

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
        """Load default demo data from package resources.

        The fallback is written in the same shape as the packaged file -- a
        name and a `content` in passwordstore format -- because that is what
        get_password() reads. It used to spell the fields out as separate keys,
        so a wheel this could not read out of turned one failure into a
        KeyError somewhere else entirely.
        """
        try:
            data_file = files("gtkpass.backends") / "data" / "demo.json"
            with data_file.open("r") as f:
                return json.load(f)
        except Exception:
            logger.warning("Could not read the packaged demo data; using a stand-in")
            return [
                {
                    "name": "example/email",
                    "content": (
                        "demo_password_123\n"
                        "username: user@example.com\n"
                        "url: https://mail.example.com\n"
                        "notes: Demo email account"
                    ),
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

        if settings.custom_data_path is None:
            return cls(demo_data=cls._load_default_data())
        return cls(demo_data=cls._read_custom_data(settings.custom_data_path))

    @staticmethod
    def _read_custom_data(path: Path) -> list[dict]:
        """Read the demo entries somebody pointed this instance at.

        The setting names a demo.json, and was read as the directory holding
        one -- so pointing it at a file did nothing at all. Both are accepted
        now, since the setting has been described as a file for long enough
        that somebody may have written a directory into it.

        A path that cannot be read is reported rather than quietly replaced
        with the built-in entries: falling back looks exactly like the setting
        having worked, which is the one reading that is never true.
        """
        demo_file = path / "demo.json" if path.is_dir() else path
        try:
            with open(demo_file) as handle:
                return json.load(handle)
        except OSError as error:
            raise BackendError(f"Could not read demo data from {demo_file}") from error
        except ValueError as error:
            raise BackendError(f"{demo_file} is not valid JSON: {error}") from error

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
