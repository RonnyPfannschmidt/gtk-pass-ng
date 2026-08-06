"""Direct backend for GTKPass.

This backend directly accesses GPG-encrypted password files on the filesystem,
similar to how the `pass` command-line tool works, but implemented entirely
in Python without spawning external processes.

Features:
- Direct GPG decryption using python-gnupg
- Scans password-store directory for .gpg files
- Supports hierarchical password organization
- Works both inside and outside flatpak
"""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import List, Optional

try:
    import gnupg
except ImportError:
    # A missing optional dependency must not break entry point loading for the
    # whole backend; is_available() reports it instead.
    gnupg = None  # type: ignore

from gtkpass.backends import BackendMetadata, PasswordBackend, PasswordEntry, BackendSettings, PasswordMetadata, BackendError

logger = logging.getLogger(__name__)


@dataclass
class DirectBackendSettings(BackendSettings):
    """Settings for direct GPG backend.
    
    Attributes:
        password_store_dir: Path to password store (None = use $PASSWORD_STORE_DIR or ~/.password-store)
        gpg_home: Optional GPG home directory (None = use default)
    """
    password_store_dir: Optional[Path] = None
    gpg_home: Optional[Path] = None


class DirectBackend(PasswordBackend):
    """Direct GPG file access backend.
    
    Reads password files directly from ~/.password-store (or $PASSWORD_STORE_DIR)
    and decrypts them using GPG.
    """
    
    metadata = BackendMetadata(
        id="direct",
        name="Direct (GPG Files)",
        icon="folder-documents-symbolic",
        description="Direct access to GPG-encrypted password files",
    )
    
    def __init__(self, password_store_dir: Path, gpg):
        """Initialize direct backend.
        
        Args:
            password_store_dir: Path to password store directory
            gpg: Initialized GPG instance
        """
        self.password_store_dir = password_store_dir
        self.gpg = gpg
        logger.info(f"Direct backend initialized with store: {self.password_store_dir}")
    
    @classmethod
    def is_available(cls) -> bool:
        """Check if direct backend is available.
        
        Returns:
            True if password store directory exists and GPG is available
        """
        if gnupg is None:
            logger.debug("python-gnupg is not installed")
            return False

        try:
            # Check for password store directory
            store_dir = os.environ.get('PASSWORD_STORE_DIR')
            if not store_dir:
                store_dir = os.path.expanduser('~/.password-store')
            
            if not os.path.isdir(store_dir):
                logger.debug(f"Password store directory not found: {store_dir}")
                return False
            
            # Check if GPG is available
            try:
                gpg = gnupg.GPG()
                # Try to list keys to verify GPG works
                gpg.list_keys()
                return True
            except Exception as e:
                logger.debug(f"GPG not available: {e}")
                return False
                
        except Exception as e:
            logger.debug(f"Direct backend not available: {e}")
            return False
    
    @classmethod
    def create(cls, settings: Optional[DirectBackendSettings] = None) -> "DirectBackend":
        """Create and initialize a backend instance.
        
        Args:
            settings: Direct backend settings (uses defaults if None)
        
        Returns:
            Initialized backend instance
        
        Raises:
            BackendError: If backend is not available or initialization fails
        """
        if not cls.is_available():
            raise BackendError(f"{cls.metadata.name} backend is not available")
        
        if settings is None:
            settings = DirectBackendSettings()
        
        # Get password store directory
        if settings.password_store_dir:
            password_store_dir = settings.password_store_dir
        else:
            store_dir = os.environ.get('PASSWORD_STORE_DIR')
            if not store_dir:
                store_dir = os.path.expanduser('~/.password-store')
            password_store_dir = Path(store_dir)
        
        if not password_store_dir.is_dir():
            raise BackendError(f"Password store directory not found: {password_store_dir}")
        
        # Initialize GPG
        gpg_home = str(settings.gpg_home) if settings.gpg_home else None
        gpg = gnupg.GPG(gnupghome=gpg_home)
        # Verify GPG works
        gpg.list_keys()
        
        return cls(password_store_dir=password_store_dir, gpg=gpg)
    
    def list_passwords(self, prefix: str = "") -> List[PasswordMetadata]:
        """List all available passwords.
        
        Returns:
            List of PasswordEntry objects
        """
        if not self.password_store_dir:
            raise RuntimeError("Backend not initialized")
        
        passwords = []
        
        # Walk the password store directory
        for gpg_file in self.password_store_dir.rglob('*.gpg'):
            # Get relative path from store root
            rel_path = gpg_file.relative_to(self.password_store_dir)
            
            # Remove .gpg extension
            password_name = str(rel_path)[:-4]  # Remove '.gpg'
            
            # Create password entry
            entry = PasswordEntry(
                backend_id=self.metadata.id,
                name=password_name,
                username="",  # Will be populated when password is retrieved
                url="",
            )
            passwords.append(entry)
        
        logger.debug(f"Found {len(passwords)} passwords in direct backend")
        return passwords
    
    def get_password(self, name: str) -> Optional[PasswordEntry]:
        """Retrieve a specific password.
        
        Args:
            name: Password name (relative path without .gpg extension)
        
        Returns:
            PasswordEntry with decrypted password, or None if not found
        """
        if not self.password_store_dir or not self.gpg:
            raise RuntimeError("Backend not initialized")
        
        # Construct full path to .gpg file
        gpg_file = self.password_store_dir / f"{name}.gpg"
        
        if not gpg_file.is_file():
            logger.warning(f"Password file not found: {gpg_file}")
            return None
        
        try:
            # Read and decrypt the file
            with open(gpg_file, 'rb') as f:
                decrypted = self.gpg.decrypt_file(f)
            
            if not decrypted.ok:
                logger.error(f"Failed to decrypt {name}: {decrypted.status}")
                return None
            
            # Parse the decrypted content
            # Format: first line is password, subsequent lines are metadata
            lines = str(decrypted).strip().split('\n')
            
            if not lines:
                logger.warning(f"Empty password file: {name}")
                return None
            
            password = lines[0]
            metadata = {}
            
            # Parse metadata from subsequent lines
            for line in lines[1:]:
                if ':' in line:
                    key, value = line.split(':', 1)
                    metadata[key.strip().lower()] = value.strip()
            
            # Extract common fields
            username = metadata.get('username', metadata.get('user', metadata.get('login', '')))
            url = metadata.get('url', metadata.get('website', metadata.get('uri', '')))
            notes_lines = []
            
            # Collect notes (any non-key:value lines)
            for line in lines[1:]:
                if ':' not in line and line.strip():
                    notes_lines.append(line)
            
            notes = '\n'.join(notes_lines) if notes_lines else ''
            
            # Create password entry
            entry = PasswordEntry(
                backend_id=self.metadata.id,
                name=name,
                username=username,
                password=password,
                url=url,
                notes=notes,
            )
            
            return entry
            
        except Exception as e:
            logger.error(f"Error retrieving password {name}: {e}")
            return None
    
    def create_password(
        self,
        name: str,
        password: str,
        username: str = "",
        url: str = "",
        notes: str = "",
    ) -> bool:
        """Create a new password entry.
        
        Args:
            name: Password name (will be file path)
            password: The password to store
            username: Username associated with password
            url: URL/website
            notes: Additional notes
        
        Returns:
            True if successful, False otherwise
        """
        if not self.password_store_dir or not self.gpg:
            raise RuntimeError("Backend not initialized")
        
        # Construct full path to .gpg file
        gpg_file = self.password_store_dir / f"{name}.gpg"
        
        # Create parent directories if needed
        gpg_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Build password file content
            content_lines = [password]
            
            if username:
                content_lines.append(f"username: {username}")
            if url:
                content_lines.append(f"url: {url}")
            if notes:
                content_lines.append(notes)
            
            content = '\n'.join(content_lines)
            
            # Get GPG recipient from .gpg-id file
            gpg_id_file = self.password_store_dir / '.gpg-id'
            if not gpg_id_file.exists():
                logger.error("No .gpg-id file found in password store")
                return False
            
            with open(gpg_id_file, 'r') as f:
                gpg_id = f.read().strip()
            
            # Encrypt the content
            encrypted = self.gpg.encrypt(
                content,
                gpg_id,
                armor=False,  # Binary format like pass does
            )
            
            if not encrypted.ok:
                logger.error(f"Failed to encrypt password: {encrypted.status}")
                return False
            
            # Write encrypted content to file
            with open(gpg_file, 'wb') as f:
                f.write(encrypted.data)
            
            logger.info(f"Created password: {name}")
            return True
            
        except Exception as e:
            logger.error(f"Error creating password {name}: {e}")
            return False
    
    def update_password(
        self,
        name: str,
        password: Optional[str] = None,
        username: Optional[str] = None,
        url: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """Update an existing password entry.
        
        Args:
            name: Password name
            password: New password (None to keep existing)
            username: New username (None to keep existing)
            url: New URL (None to keep existing)
            notes: New notes (None to keep existing)
        
        Returns:
            True if successful, False otherwise
        """
        # Get existing entry
        existing = self.get_password(name)
        if not existing:
            logger.error(f"Password not found for update: {name}")
            return False
        
        # Use new values or fall back to existing
        new_password = password if password is not None else existing.password
        new_username = username if username is not None else existing.username
        new_url = url if url is not None else existing.url
        new_notes = notes if notes is not None else existing.notes
        
        # Create updated password (overwrites existing)
        return self.create_password(
            name=name,
            password=new_password,
            username=new_username,
            url=new_url,
            notes=new_notes,
        )
    
    def delete_password(self, name: str) -> bool:
        """Delete a password entry.
        
        Args:
            name: Password name to delete
        
        Returns:
            True if successful, False otherwise
        """
        if not self.password_store_dir:
            raise RuntimeError("Backend not initialized")
        
        gpg_file = self.password_store_dir / f"{name}.gpg"
        
        if not gpg_file.is_file():
            logger.error(f"Password file not found for deletion: {name}")
            return False
        
        try:
            gpg_file.unlink()
            logger.info(f"Deleted password: {name}")
            
            # Remove empty parent directories
            parent = gpg_file.parent
            while parent != self.password_store_dir:
                try:
                    if not any(parent.iterdir()):
                        parent.rmdir()
                        parent = parent.parent
                    else:
                        break
                except Exception:
                    break
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting password {name}: {e}")
            return False
