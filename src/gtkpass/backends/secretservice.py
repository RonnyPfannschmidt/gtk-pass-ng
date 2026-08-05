"""Secret Service backend for GTKPass.

Provides integration with GNOME Keyring, KWallet, and other Secret Service
compatible keyrings using the secretstorage library.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

try:
    import secretstorage
except ImportError:
    secretstorage = None  # type: ignore

from . import PasswordBackend, PasswordEntry, PasswordMetadata, BackendError, BackendMetadata, BackendSettings


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
        """Check if Secret Service backend is available.
        
        Returns:
            True if secretstorage is installed and Secret Service is accessible
        """
        if secretstorage is None:
            return False
        
        try:
            connection = secretstorage.dbus_init()
            secretstorage.get_default_collection(connection)
            connection.close()
            return True
        except Exception as e:
            # Log the reason for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"Secret Service not available: {type(e).__name__}: {e}")
            return False
    
    @classmethod
    def create(cls, settings: Optional[SecretServiceBackendSettings] = None) -> "SecretServiceBackend":
        """Create and initialize a backend instance.
        
        Args:
            settings: Secret Service backend settings (uses defaults if None)
        
        Returns:
            Initialized backend instance
        
        Raises:
            BackendError: If backend is not available or initialization fails
        """
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
    
    def _get_items(self, name: Optional[str] = None) -> List:
        """Check if Secret Service backend is available.
        
        Returns:
            True if secretstorage is installed and Secret Service is accessible
        """
        if secretstorage is None:
            return False
        
        try:
            connection = secretstorage.dbus_init()
            secretstorage.get_default_collection(connection)
            connection.close()
            return True
        except Exception:
            return False
    
    def _get_items(self, name: Optional[str] = None) -> List:
        """Get items from collection.
        
        Args:
            name: Optional name filter
        
        Returns:
            List of secret items
        """
        # Get all items from the collection instead of filtering by application
        # This allows us to see all passwords in the keyring, not just gtkpass-created ones
        if name:
            # If a specific name is requested, search for it
            attributes = {"application": self.APPLICATION_NAME, "name": name}
            return list(self._collection.search_items(attributes))
        else:
            # Get all items in the collection
            return list(self._collection.get_all_items())
    
    def list_passwords(self, prefix: str = "") -> List[PasswordMetadata]:
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
                attrs = item.get_attributes()
                # Use the label as the name if no "name" attribute exists
                # This allows us to show all keyring items with their labels
                name = attrs.get("name", item.get_label())
                
                # Skip items with empty names/labels
                if not name or not name.strip():
                    continue
                
                if not prefix or name.startswith(prefix):
                    metadata = PasswordMetadata(
                        name=name,
                        path=Path(f"secretservice://{name}"),
                        modified=item.get_modified() / 1000000000.0,  # nanoseconds to seconds
                    )
                    results.append(metadata)
        
        except Exception as e:
            raise BackendError(f"Failed to list passwords: {e}")
        
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
            raise BackendError(f"Failed to get password '{name}': {e}")
    
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
            raise BackendError(f"Failed to add password '{name}': {e}")
    
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
            
            # Update item
            item.set_secret(password.encode("utf-8"))
            item.set_attributes(attributes)
        
        except FileNotFoundError:
            raise
        except Exception as e:
            raise BackendError(f"Failed to edit password '{name}': {e}")
    
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
            raise BackendError(f"Failed to delete password '{name}': {e}")
    
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
            raise BackendError(f"Failed to move password: {e}")
    
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
    
    def search(self, query: str) -> List[PasswordMetadata]:
        """Search for passwords matching query.
        
        Args:
            query: Search query (case-insensitive)
        
        Returns:
            List of matching password metadata entries
        """
        query_lower = query.lower()
        all_passwords = self.list_passwords()
        
        results = [
            pwd for pwd in all_passwords
            if query_lower in pwd.name.lower()
        ]
        
        return sorted(results, key=lambda x: x.name)
