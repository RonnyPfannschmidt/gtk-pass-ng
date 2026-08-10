"""Secret Service backend for GTKPass.

Provides integration with GNOME Keyring, KWallet, and other Secret Service
compatible keyrings using the secretstorage library.
"""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

try:
    import secretstorage
except ImportError:
    secretstorage = None  # type: ignore

from gtkpass.safety import ensure_keyring_allowed, opted_in

from . import (
    BackendError,
    BackendMetadata,
    BackendSettings,
    PasswordBackend,
    PasswordEntry,
    PasswordMetadata,
)

logger = logging.getLogger(__name__)

#: is_available() runs on the UI thread while the window is being built, and the
#: D-Bus round trip below has no timeout of its own: with no Secret Service on
#: the bus it blocks indefinitely and the application never finishes starting.
AVAILABILITY_TIMEOUT_SECONDS = 5.0


@dataclass
class SecretServiceBackendSettings(BackendSettings):
    """Settings for Secret Service backend.

    Attributes:
        collection_name: Name of the collection to use (default: "Login")
    """

    collection_name: str = "Login"


class SecretServiceBackend(PasswordBackend):
    """Secret Service backend using secretstorage.

    Integrates with GNOME Keyring, KWallet, and other Secret Service API
    compatible password managers via DBus. Stores passwords in the default
    "Login" collection following standard GNOME conventions.

    Requires:
        - secretstorage package
        - DBus session bus
        - Secret Service daemon (gnome-keyring-daemon, kwallet, etc.)
    """

    metadata = BackendMetadata(
        id="secretservice",
        name="Secret Service",
        icon="dialog-password-symbolic",
        description="System keyring (GNOME/KDE)",
    )

    APPLICATION_NAME = "gtkpass"

    def __init__(self, connection, collection):
        """Initialize Secret Service backend.

        Args:
            connection: DBus connection
            collection: Secret Service collection
        """
        self._connection = connection
        self._collection = collection

    @classmethod
    def is_available(cls) -> bool:
        """Whether a Secret Service is reachable, answering within a deadline.

        Returns:
            True if secretstorage is installed and Secret Service is accessible
        """
        if secretstorage is None:
            return False

        # Probing opens the user's default collection, which is real secrets and
        # may prompt them to unlock. Availability has to answer rather than
        # raise, so this reports unavailable instead.
        if not opted_in():
            logger.debug(
                "Not probing the keyring: %s is not set", "GTKPASS_ALLOW_REAL_STORE"
            )
            return False

        outcome: list[bool] = []

        def probe() -> None:
            try:
                connection = secretstorage.dbus_init()
                try:
                    secretstorage.get_default_collection(connection)
                finally:
                    connection.close()
            except Exception as e:
                logger.debug(
                    "Secret Service not available: %s: %s", type(e).__name__, e
                )
                outcome.append(False)
            else:
                outcome.append(True)

        # Daemon thread: if the bus call never returns there is nothing to
        # cancel, but it must not keep the process alive either.
        thread = threading.Thread(target=probe, daemon=True, name="secretservice-probe")
        thread.start()
        thread.join(AVAILABILITY_TIMEOUT_SECONDS)

        if not outcome:
            logger.warning(
                "Secret Service did not respond within %ss; treating as unavailable",
                AVAILABILITY_TIMEOUT_SECONDS,
            )
            return False
        return outcome[0]

    @classmethod
    def create(
        cls, settings: SecretServiceBackendSettings | None = None
    ) -> "SecretServiceBackend":
        """Create and initialize a backend instance.

        Args:
            settings: Secret Service backend settings (uses defaults if None)

        Returns:
            Initialized backend instance

        Raises:
            BackendError: If backend is not available or initialization fails
            RealStoreBlocked: If this is not the application being used
        """
        # Before is_available(), which reports rather than raises: a caller that
        # should not be here deserves to be told why, not left with a bland
        # "not available".
        ensure_keyring_allowed()

        if not cls.is_available():
            raise BackendError(f"{cls.metadata.name} backend is not available")

        if settings is None:
            settings = SecretServiceBackendSettings()

        # Connect to Secret Service
        connection = secretstorage.dbus_init()
        collections = secretstorage.get_all_collections(connection)

        # Find the requested collection
        collection = None
        for coll in collections:
            if coll.get_label() == settings.collection_name:
                collection = coll
                break

        if collection is None:
            # Try to unlock the default collection
            default_coll = secretstorage.get_default_collection(connection)
            if default_coll:
                collection = default_coll
            else:
                raise BackendError(f"Collection '{settings.collection_name}' not found")

        # Unlock collection if locked
        if collection.is_locked():
            collection.unlock()

        return cls(connection=connection, collection=collection)

    @staticmethod
    def _name_of(item) -> str:
        """What an item is called in the sidebar.

        Its `name` attribute when it has one, which is what GTKPass writes, and
        otherwise its label, which is all another application will have set.
        """
        return item.get_attributes().get("name") or item.get_label() or ""

    def _get_items(self, name: str | None = None) -> list:
        """Items in the collection, all of them or the ones by that name.

        Looking a name up used to search for `application=gtkpass`, while the
        listing showed the whole keyring. Every row the sidebar offered from
        another application therefore answered "not found" when it was selected.
        The name is resolved the same way it was displayed instead.
        """
        items = list(self._collection.get_all_items())
        if name is None:
            return items
        return [item for item in items if self._name_of(item) == name]

    def list_passwords(self, prefix: str = "") -> list[PasswordMetadata]:
        """List all passwords, optionally filtered by prefix.

        Args:
            prefix: Optional prefix to filter results

        Returns:
            List of password metadata (content not loaded)
        """
        results = []

        try:
            items = self._get_items()

            for item in items:
                name = self._name_of(item)

                # Skip items with empty names/labels
                if not name or not name.strip():
                    continue

                if not prefix or name.startswith(prefix):
                    metadata = PasswordMetadata(
                        name=name,
                        path=Path(f"secretservice://{name}"),
                        modified=item.get_modified()
                        / 1000000000.0,  # nanoseconds to seconds
                    )
                    results.append(metadata)

        except Exception as e:
            raise BackendError(f"Failed to list passwords: {e}") from e

        return sorted(results, key=lambda x: x.name)

    def get_password(self, name: str) -> PasswordEntry:
        """Get a specific password entry.

        Args:
            name: Name of the password

        Returns:
            Password entry with content loaded

        Raises:
            FileNotFoundError: If password doesn't exist
            BackendError: If retrieval fails
        """
        try:
            items = self._get_items(name)

            if not items:
                raise FileNotFoundError(f"Password '{name}' not found")

            item = items[0]  # Should only be one with this name
            secret = item.get_secret().decode("utf-8")
            attrs = item.get_attributes()

            # Build content in password-store format
            # First line: password
            # Following lines: key: value metadata
            content_lines = [secret]

            # Add metadata from attributes
            for key, value in sorted(attrs.items()):
                if key not in ["application", "name"] and value:
                    content_lines.append(f"{key}: {value}")

            content = "\n".join(content_lines)

            return PasswordEntry(
                name=name,
                path=Path(f"secretservice://{name}"),
                content=content,
            )

        except FileNotFoundError:
            raise
        except Exception as e:
            raise BackendError(f"Failed to get password '{name}': {e}") from e

    def add_password(self, name: str, content: str, commit: bool = True) -> None:
        """Add a new password entry.

        Args:
            name: Name for the password
            content: Password content (password on first line, metadata after)
            commit: Ignored for Secret Service backend

        Raises:
            FileExistsError: If password already exists
            BackendError: If creation fails
        """
        # Check if already exists
        if self._get_items(name):
            raise FileExistsError(f"Password '{name}' already exists")

        try:
            # Parse content
            lines = content.split("\n")
            password = lines[0] if lines else ""

            # Build attributes
            attributes = {
                "application": self.APPLICATION_NAME,
                "name": name,
            }

            # Parse metadata
            for line in lines[1:]:
                line = line.strip()
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if key and value:
                        attributes[key] = value

            # Create item
            self._collection.create_item(
                label=name,
                attributes=attributes,
                secret=password.encode("utf-8"),
                replace=False,
            )

        except FileExistsError:
            raise
        except Exception as e:
            raise BackendError(f"Failed to add password '{name}': {e}") from e

    def edit_password(self, name: str, content: str, commit: bool = True) -> None:
        """Edit an existing password entry.

        Args:
            name: Name of the password to edit
            content: New password content
            commit: Ignored for Secret Service backend

        Raises:
            FileNotFoundError: If password doesn't exist
            BackendError: If update fails
        """
        try:
            items = self._get_items(name)

            if not items:
                raise FileNotFoundError(f"Password '{name}' not found")

            item = items[0]

            # Parse content
            lines = content.split("\n")
            password = lines[0] if lines else ""

            # Start from what the item already carries rather than replacing it.
            # Attributes are how an application finds its own item again, so
            # writing GTKPass's parsed set over a Chromium or NetworkManager
            # entry would leave it in the keyring and unreachable by its owner
            # -- silently, and long after the edit. setdefault, so an item
            # GTKPass did not create keeps saying so.
            attributes = item.get_attributes()
            attributes.setdefault("application", self.APPLICATION_NAME)
            attributes.setdefault("name", name)

            # Parse metadata
            for line in lines[1:]:
                line = line.strip()
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if key and value:
                        attributes[key] = value

            # Update item
            item.set_secret(password.encode("utf-8"))
            item.set_attributes(attributes)

        except FileNotFoundError:
            raise
        except Exception as e:
            raise BackendError(f"Failed to edit password '{name}': {e}") from e

    def delete_password(self, name: str, commit: bool = True) -> None:
        """Delete a password entry.

        Args:
            name: Name of the password to delete
            commit: Ignored for Secret Service backend

        Raises:
            FileNotFoundError: If password doesn't exist
            BackendError: If deletion fails
        """
        try:
            items = self._get_items(name)

            if not items:
                raise FileNotFoundError(f"Password '{name}' not found")

            item = items[0]
            item.delete()

        except FileNotFoundError:
            raise
        except Exception as e:
            raise BackendError(f"Failed to delete password '{name}': {e}") from e

    def move_password(self, old_name: str, new_name: str, commit: bool = True) -> None:
        """Move/rename a password entry.

        Args:
            old_name: Current name of the password
            new_name: New name for the password
            commit: Ignored for Secret Service backend

        Raises:
            FileNotFoundError: If old password doesn't exist
            FileExistsError: If new name already exists
            BackendError: If move fails
        """
        # Check destination doesn't exist
        if self._get_items(new_name):
            raise FileExistsError(f"Password '{new_name}' already exists")

        try:
            items = self._get_items(old_name)

            if not items:
                raise FileNotFoundError(f"Password '{old_name}' not found")

            item = items[0]

            # Update name in attributes
            attributes = item.get_attributes()
            attributes["name"] = new_name
            item.set_attributes(attributes)
            item.set_label(new_name)

        except (FileNotFoundError, FileExistsError):
            raise
        except Exception as e:
            raise BackendError(f"Failed to move password: {e}") from e

    def copy_password(self, source: str, dest: str, commit: bool = True) -> None:
        """Copy a password entry.

        Args:
            source: Name of the password to copy
            dest: Name for the copy
            commit: Ignored for Secret Service backend

        Raises:
            FileNotFoundError: If source doesn't exist
            FileExistsError: If destination already exists
            BackendError: If copy fails
        """
        # Get source entry
        entry = self.get_password(source)

        # Add as new entry
        self.add_password(dest, entry.content or "", commit)

    def search(self, query: str) -> list[PasswordMetadata]:
        """Search for passwords matching query.

        Args:
            query: Search query (case-insensitive)

        Returns:
            List of matching password metadata entries
        """
        query_lower = query.lower()
        all_passwords = self.list_passwords()

        results = [pwd for pwd in all_passwords if query_lower in pwd.name.lower()]

        return sorted(results, key=lambda x: x.name)
