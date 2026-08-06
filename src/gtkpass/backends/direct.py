"""Native GPG backend.

Reads and writes a passwordstore-format directory directly, using python-gnupg
rather than shelling out to the ``pass`` script.  Storage layout and file format
are the same, so a store is usable from either.
"""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

try:
    import gnupg
except ImportError:
    # A missing optional dependency must not break entry point loading for the
    # whole backend; is_available() reports it instead.
    gnupg = None  # type: ignore

from gtkpass.backends import (
    BackendError,
    BackendMetadata,
    BackendSettings,
    GPGError,
    PasswordBackend,
    PasswordEntry,
    PasswordMetadata,
)
from gtkpass.safety import default_store_dir, ensure_store_allowed

logger = logging.getLogger(__name__)


@dataclass
class DirectBackendSettings(BackendSettings):
    """Settings for the native GPG backend.

    Attributes:
        password_store_dir: Path to password store
            (None = use $PASSWORD_STORE_DIR or ~/.password-store)
        gpg_home: Optional GPG home directory (None = use default)
    """

    password_store_dir: Path | None = None
    gpg_home: Path | None = None


class DirectBackend(PasswordBackend):
    """Passwordstore access without the ``pass`` script."""

    metadata = BackendMetadata(
        id="direct",
        name="Direct (GPG Files)",
        icon="folder-documents-symbolic",
        description="Direct access to GPG-encrypted password files",
    )

    def __init__(self, password_store_dir: Path, gpg):
        self.password_store_dir = password_store_dir
        self.gpg = gpg
        logger.info("Direct backend initialised with store: %s", password_store_dir)

    @classmethod
    def is_available(cls) -> bool:
        """Whether GPG can be used at all.

        Deliberately says nothing about any particular store: create() is given
        the configured directory and validates that itself. Checking the default
        location here made a configured store report itself unavailable.
        """
        if gnupg is None:
            logger.debug("python-gnupg is not installed")
            return False
        if shutil.which("gpg") is None:
            logger.debug("no gpg binary on PATH")
            return False
        return True

    @classmethod
    def create(cls, settings: BackendSettings | None = None) -> "DirectBackend":
        if not cls.is_available():
            raise BackendError(f"{cls.metadata.name} backend is not available")

        if settings is None:
            settings = DirectBackendSettings()
        if not isinstance(settings, DirectBackendSettings):
            raise BackendError(f"expected DirectBackendSettings, got {type(settings)}")

        store = settings.password_store_dir or default_store_dir()
        ensure_store_allowed(store)
        if not store.is_dir():
            raise BackendError(f"Password store directory not found: {store}")

        gpg_home = str(settings.gpg_home) if settings.gpg_home else None
        try:
            gpg = gnupg.GPG(gnupghome=gpg_home)
            gpg.list_keys()
        except Exception as e:
            raise GPGError(f"Could not initialise GPG: {e}") from e

        return cls(password_store_dir=store, gpg=gpg)

    # -- paths and recipients ------------------------------------------------

    def _path_for(self, name: str) -> Path:
        """Resolve an entry name to its file, refusing to escape the store."""
        candidate = (self.password_store_dir / f"{name}.gpg").resolve()
        root = self.password_store_dir.resolve()
        if not candidate.is_relative_to(root):
            raise BackendError(f"'{name}' is outside the password store")
        return candidate

    def _recipients_for(self, path: Path) -> list[str]:
        """Recipients from the nearest .gpg-id, searching upwards.

        pass allows a subdirectory to carry its own .gpg-id so a subtree can be
        shared with a different set of people. Reading only the store root would
        silently encrypt those entries to the wrong key.
        """
        root = self.password_store_dir.resolve()
        directory = path.resolve().parent
        while True:
            gpg_id = directory / ".gpg-id"
            if gpg_id.is_file():
                recipients = [
                    line.strip()
                    for line in gpg_id.read_text().splitlines()
                    if line.strip() and not line.startswith("#")
                ]
                if recipients:
                    return recipients
            if directory == root or root not in directory.parents:
                break
            directory = directory.parent
        raise BackendError(
            f"No .gpg-id found for '{path.name}'. Run 'pass init <gpg-id>' first."
        )

    def _encrypt_to_file(self, path: Path, content: str) -> None:
        recipients = self._recipients_for(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        result = self.gpg.encrypt(
            content, recipients, armor=False, output=str(path), always_trust=True
        )
        if not result.ok:
            raise GPGError(f"Failed to encrypt '{path.name}': {result.status}")

    # -- reading -------------------------------------------------------------

    def list_passwords(self, prefix: str = "") -> list[PasswordMetadata]:
        entries = []
        for gpg_file in sorted(self.password_store_dir.rglob("*.gpg")):
            relative = gpg_file.relative_to(self.password_store_dir)
            # Skip repository internals; .git can hold .gpg objects of its own.
            if any(part.startswith(".") for part in relative.parts):
                continue
            name = str(relative)[: -len(".gpg")]
            if prefix and not name.startswith(prefix):
                continue
            entries.append(
                PasswordMetadata(
                    name=name, path=gpg_file, modified=gpg_file.stat().st_mtime
                )
            )
        logger.debug("Found %d passwords in %s", len(entries), self.password_store_dir)
        return entries

    def get_password(self, name: str) -> PasswordEntry:
        path = self._path_for(name)
        if not path.is_file():
            raise FileNotFoundError(f"No password named '{name}'")

        with open(path, "rb") as handle:
            decrypted = self.gpg.decrypt_file(handle)
        if not decrypted.ok:
            raise GPGError(f"Failed to decrypt '{name}': {decrypted.status}")

        return PasswordEntry(name=name, path=path, content=str(decrypted))

    def search(self, query: str) -> list[PasswordMetadata]:
        """Match names only.

        Searching content would mean decrypting the whole store, prompting for
        the passphrase and defeating the point of it being encrypted at rest.
        """
        lowered = query.lower()
        return [
            entry for entry in self.list_passwords() if lowered in entry.name.lower()
        ]

    # -- writing -------------------------------------------------------------

    def add_password(self, name: str, content: str, commit: bool = True) -> None:
        path = self._path_for(name)
        if path.exists():
            raise FileExistsError(f"'{name}' already exists")
        self._encrypt_to_file(path, content)

    def edit_password(self, name: str, content: str, commit: bool = True) -> None:
        path = self._path_for(name)
        if not path.is_file():
            raise FileNotFoundError(f"No password named '{name}'")
        self._encrypt_to_file(path, content)

    def delete_password(self, name: str, commit: bool = True) -> None:
        path = self._path_for(name)
        if not path.is_file():
            raise FileNotFoundError(f"No password named '{name}'")
        path.unlink()
        self._prune_empty_parents(path.parent)

    def move_password(self, old_name: str, new_name: str, commit: bool = True) -> None:
        source = self._path_for(old_name)
        destination = self._path_for(new_name)
        if not source.is_file():
            raise FileNotFoundError(f"No password named '{old_name}'")
        if destination.exists():
            raise FileExistsError(f"'{new_name}' already exists")
        self._reencrypt_or_rename(source, destination)
        self._prune_empty_parents(source.parent)

    def copy_password(self, source: str, dest: str, commit: bool = True) -> None:
        source_path = self._path_for(source)
        dest_path = self._path_for(dest)
        if not source_path.is_file():
            raise FileNotFoundError(f"No password named '{source}'")
        if dest_path.exists():
            raise FileExistsError(f"'{dest}' already exists")
        self._reencrypt_or_rename(source_path, dest_path, keep_source=True)

    def _reencrypt_or_rename(
        self, source: Path, destination: Path, keep_source: bool = False
    ) -> None:
        """Move or copy, re-encrypting when the recipients differ.

        A plain rename across a .gpg-id boundary would leave the file readable
        by the wrong people, which pass avoids by re-encrypting.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        if self._recipients_for(source) == self._recipients_for(destination):
            if keep_source:
                shutil.copy2(source, destination)
            else:
                source.rename(destination)
            return

        with open(source, "rb") as handle:
            decrypted = self.gpg.decrypt_file(handle)
        if not decrypted.ok:
            raise GPGError(f"Failed to decrypt '{source.name}': {decrypted.status}")
        self._encrypt_to_file(destination, str(decrypted))
        if not keep_source:
            source.unlink()

    def _prune_empty_parents(self, directory: Path) -> None:
        """Remove directories left empty, up to but excluding the store root."""
        root = self.password_store_dir.resolve()
        directory = directory.resolve()
        while directory != root and root in directory.parents:
            if any(directory.iterdir()):
                break
            directory.rmdir()
            directory = directory.parent
