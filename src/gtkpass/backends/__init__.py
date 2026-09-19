"""Backend base classes and interfaces for password storage."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Only for the annotation below: recipients imports from this module at
    # runtime, and naming it here for real would close the circle.
    from .recipients import RecipientAudit

#: How long a backend may leave a subprocess running before it is treated as
#: stuck, in seconds.
#:
#: Shared by every subprocess GTKPass owns -- git in ``git_store``, pass in
#: ``pass_cli`` -- because the reason is the same in both places and one number
#: is easier to reason about than two. None of these commands is interactive
#: from GTKPass's side: git is run in an environment where it cannot ask a
#: question, and pass reads its input from stdin.
#:
#: What pass *can* do is raise a pinentry prompt, which is a person typing a
#: passphrase rather than a hung process, so this has to be patient enough for
#: that. Two minutes is: a prompt left unanswered that long has been abandoned,
#: and abandoning it back costs a retry rather than an entry.
#:
#: The deadline matters because the manager's pool has four workers and the
#: window quits by shutting that pool down. A command with no deadline is a
#: worker that never returns.
SUBPROCESS_TIMEOUT_SECONDS = 120

#: A line that is nothing but a URI, captured with its scheme.
#:
#: pass-otp writes ``otpauth://`` on a line of its own, and people paste bare
#: URLs the same way. Splitting those on the first colon produced the key
#: ``otpauth`` with the value ``//totp/...``: a field whose value was no longer
#: the URI it came from.
_URI_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://\S*$")


def metadata_pair(line: str) -> tuple[str, str] | None:
    """Read one line below the password as a field, or decide it is prose.

    The one rule both halves of the interface follow. `pass` prescribes no
    format for what sits under the password, so this is a convention rather
    than a specification: a line is a field when its colon is followed by
    whitespace or ends the line, which is how every store and every other
    frontend writes one. Everything else is prose, and the detail pane shows it
    as notes.

    The two have to agree, because they divide the same lines between them. The
    pane used to keep a line only when it had no colon anywhere in it while
    this counted every colon as a separator, and a sentence like "the safe
    opens at 10:30" fell between the two: shown as neither, and lost without a
    word.

    Returns:
        The lowercased key and its value, or None for a line that is prose.
    """
    line = line.strip()
    if not line:
        return None

    uri = _URI_LINE.match(line)
    if uri:
        # The whole line is the value: the scheme names it, it does not
        # introduce it.
        return uri.group(1).lower(), line

    key, separator, value = line.partition(":")
    if not separator or not key.strip():
        return None
    if value and not value[:1].isspace():
        # A colon inside a word -- a time, a ratio, a path -- rather than one
        # separating a name from what it holds.
        return None
    return key.strip().lower(), value.strip()


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
        """The ``key: value`` fields written below the password.

        Returns:
            One entry per field line, keyed by its lowercased name. Lines that
            are prose rather than fields are not here; the detail pane shows
            those as notes, and :func:`metadata_pair` is the single rule that
            decides which a line is.
        """
        if not self.content:
            return {}

        metadata = {}
        for line in self.content.split("\n")[1:]:  # Skip password line
            pair = metadata_pair(line)
            if pair is not None:
                metadata[pair[0]] = pair[1]
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


class SyncUnavailable(Enum):
    """Why a store cannot sync.

    Each value has a different remedy -- install git, run `git init`, add a
    remote, move the store out of the repository it is nested in -- so they are
    not collapsed into a single boolean.
    """

    READY = "ready"
    NO_GIT = "no-git"
    NOT_A_REPO = "not-a-repo"
    NESTED_IN_ANOTHER_REPO = "nested-in-another-repo"
    NO_REMOTE = "no-remote"
    NOT_OFFERED = "not-offered"
    NO_STORE = "no-store"


@dataclass(frozen=True)
class SyncCapability:
    """Whether a backend instance can sync, and what to say when it cannot.

    ``detail`` is shown to the user as the sync button's tooltip, so it reads as
    a sentence rather than as a reason code.
    """

    supported: bool
    reason: SyncUnavailable
    detail: str
    remote: str | None = None
    branch: str | None = None

    @classmethod
    def unsupported(cls, reason: SyncUnavailable, detail: str) -> "SyncCapability":
        return cls(supported=False, reason=reason, detail=detail)


@dataclass(frozen=True)
class SyncResult:
    """What a sync moved, for the confirmation message."""

    pulled: int
    pushed: int


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

    #: Whether entries can be added, edited and deleted through this backend.
    #:
    #: The interface offers all three and the demo backend raises on every one
    #: of them, so without something to ask beforehand the only way to find out
    #: is to offer somebody a dialog, let them fill it in and refuse it
    #: afterwards. Writable is the default: a backend that cannot write says so.
    writable: bool = True

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

    def move_folder(
        self, old_prefix: str, new_prefix: str, commit: bool = True
    ) -> None:
        """Move every entry under a folder, keeping their paths below it.

        Deliberately not abstract. A folder is a naming convention, not a thing
        every backend has: the keyring has no directories at all -- an item
        called ``work/mail`` is one item whose name contains a slash -- so this
        moves the entries one at a time, which works wherever
        :meth:`move_password` does. A backend with a cheaper way to do it says
        so by overriding, and `pass mv` on a directory is exactly that.

        The clash check happens over the whole folder before anything moves.
        Finding it on the way to the third entry would leave two of them
        renamed and the folder in neither place, which is worse than refusing.

        Args:
            old_prefix: The folder's path today, without a trailing slash.
            new_prefix: The path it is to have.
            commit: Whether to commit to git (if enabled)

        Raises:
            FileNotFoundError: If no entry lives under ``old_prefix``.
            FileExistsError: If any entry would land on one that is already
                there.
            ValueError: If the folder would be moved into itself, or onto
                itself -- neither of which is a rename that means anything.
        """
        moves = self.plan_folder_move(old_prefix, new_prefix)
        for old_name, new_name in moves:
            self.move_password(old_name, new_name, commit)

    def plan_folder_move(
        self, old_prefix: str, new_prefix: str
    ) -> list[tuple[str, str]]:
        """Work out what a folder move would do, and refuse it if it cannot.

        Separate from :meth:`move_folder` so that a backend overriding the move
        still refuses the same things for the same reasons -- and so that the
        interface can ask what a move would touch before offering it.

        Returns:
            (old name, new name) for every entry under the folder.

        Raises:
            FileNotFoundError, FileExistsError, ValueError: As move_folder.
        """
        old_prefix = old_prefix.strip("/")
        new_prefix = new_prefix.strip("/")
        if not old_prefix or not new_prefix:
            raise ValueError("A folder move needs a folder at both ends")
        if old_prefix == new_prefix:
            raise ValueError(f"'{old_prefix}' is already where it is")
        if new_prefix.startswith(f"{old_prefix}/"):
            raise ValueError(f"'{old_prefix}' cannot be moved inside itself")

        # The trailing slash is the whole of the correctness here. Matching on
        # the bare prefix takes "workshop" along with "work", which is a rename
        # of entries nobody was looking at.
        held = [
            entry.name
            for entry in self.list_passwords(prefix=f"{old_prefix}/")
            if entry.name.startswith(f"{old_prefix}/")
        ]
        if not held:
            raise FileNotFoundError(f"No folder named '{old_prefix}'")

        existing = {entry.name for entry in self.list_passwords()}
        moves = [(name, f"{new_prefix}/{name[len(old_prefix) + 1 :]}") for name in held]
        clashes = sorted(new for _, new in moves if new in existing)
        if clashes:
            raise FileExistsError(f"'{clashes[0]}' already exists")
        return moves

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

    # -- syncing -------------------------------------------------------------
    #
    # Deliberately not abstract. A backend with no filesystem store -- the
    # keyring, the demo data -- can never sync, and making these abstract would
    # force every one of them, and every third-party backend, to write a stub
    # that says so. The default already says so.

    def sync_capability(self) -> SyncCapability:
        """Whether this instance can sync with a remote, and why not if it cannot.

        Must not block: this is consulted to decide whether the sync button is
        sensitive. Implementations probe once when they are created rather than
        shelling out here.
        """
        return SyncCapability.unsupported(
            SyncUnavailable.NO_STORE,
            f"{self.metadata.name} has no password store to sync.",
        )

    def sync(self) -> SyncResult:
        """Pull from the remote, then push.

        Raises:
            GitError: If the sync fails, including SyncNotPermitted when the
                sandbox was not granted the permissions it needs.
            BackendError: If this backend cannot sync at all.
        """
        raise BackendError(f"{self.metadata.name} cannot sync.")

    def unpushed_commits(self) -> int:
        """How many local commits the remote has not seen.

        Zero for a backend that cannot sync, which is why this is not
        abstract. May run git, so it is called off the UI thread; the sidebar
        shows the answer beside the store.
        """
        return 0

    # -- recipients ----------------------------------------------------------

    def recipient_audit(self) -> "RecipientAudit | None":
        """Whether who this store is encrypted to has changed since it was approved.

        None for a backend that has no .gpg-id to read -- the keyring, the demo
        data -- which is why this is not abstract. Answered from what the
        backend found when it was built, so it does not block.
        """
        return None


class BackendError(Exception):
    """Base exception for backend errors."""

    pass


class GPGError(BackendError):
    """Exception for GPG-related errors."""

    pass


class GitError(BackendError):
    """Exception for git-related errors."""

    pass


class RecipientsChanged(BackendError):
    """A store's recipients differ from the set last approved for it.

    Raised instead of writing. Encrypting now would encrypt to whoever the file
    names today, and the whole question is whether that is who it should name --
    so the write waits for a person to say. Reading is unaffected: nothing newly
    named can decrypt what is already there.

    ``audit`` carries the RecipientAudit, so the interface can show what changed
    without asking the store again.
    """

    def __init__(self, message: str, audit) -> None:
        super().__init__(message)
        self.audit = audit


class SyncNotPermitted(GitError):
    """Sync needs a sandbox permission the user has not granted.

    A GitError so that ``except GitError`` around a sync still catches it, but
    distinct because the remedy is a command to run rather than anything about
    the store. Raised before any git process starts.
    """

    def __init__(self, message: str, override_command: str) -> None:
        super().__init__(message)
        self.override_command = override_command
