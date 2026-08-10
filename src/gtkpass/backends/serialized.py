"""One backend, used one call at a time.

Every backend operation runs on the manager's four-worker pool, so a save, a
sync and two decrypts can all be inside the same backend at once. Nothing in the
backends is written for that:

- The Direct and Pass backends each own a :class:`~gtkpass.backends.git_store.
  GitStore` over one directory. A commit landing while ``git pull --rebase`` is
  running collides on ``.git/index.lock``, and the loser is whichever one git
  chooses to fail.
- The Secret Service backend shares a single D-Bus connection between every
  call. Two calls on it at once interleave on the same socket.
- A decrypt reads a ``.gpg`` file. Reading one while git is rewriting the
  worktree can read a file that is half of another revision.

So the manager hands out one of these rather than the backend itself, and the
operations happen in turn. It costs nothing in the ordinary case -- the
interface starts one thing at a time -- and it is the difference between a
queued save and a damaged store when it does not.

``sync_capability()`` and ``metadata`` are deliberately outside the lock. They
answer out of state fixed when the backend was built, and the sync action reads
them on the UI thread; behind the lock, deciding whether a button should be grey
would wait for a decrypt to finish.
"""

import threading

from . import (
    PasswordBackend,
    PasswordEntry,
    PasswordMetadata,
    SyncCapability,
    SyncResult,
)


class SerializedBackend(PasswordBackend):
    """Forwards to a backend, one caller at a time."""

    def __init__(self, backend: PasswordBackend) -> None:
        self._backend = backend
        # Reentrant, so a backend that reaches one of its own operations
        # through this proxy queues behind itself rather than deadlocking.
        self._lock = threading.RLock()
        # A proxy has to answer as the backend it stands for: the sidebar and
        # the manager both read this.
        self.metadata = backend.metadata

    @property
    def wrapped(self) -> PasswordBackend:
        """The backend underneath, for whoever needs its own type."""
        return self._backend

    @classmethod
    def is_available(cls) -> bool:
        """True by construction: one of these only exists around a built backend.

        The abstract method is a question about a backend *class* -- whether the
        system can support it at all -- and this class is not one anybody
        configures.
        """
        return True

    # -- reading -------------------------------------------------------------

    def list_passwords(self, prefix: str = "") -> list[PasswordMetadata]:
        with self._lock:
            return self._backend.list_passwords(prefix)

    def get_password(self, name: str) -> PasswordEntry:
        with self._lock:
            return self._backend.get_password(name)

    def search(self, query: str) -> list[PasswordMetadata]:
        with self._lock:
            return self._backend.search(query)

    # -- writing -------------------------------------------------------------

    def add_password(self, name: str, content: str, commit: bool = True) -> None:
        with self._lock:
            self._backend.add_password(name, content, commit)

    def edit_password(self, name: str, content: str, commit: bool = True) -> None:
        with self._lock:
            self._backend.edit_password(name, content, commit)

    def delete_password(self, name: str, commit: bool = True) -> None:
        with self._lock:
            self._backend.delete_password(name, commit)

    def move_password(self, old_name: str, new_name: str, commit: bool = True) -> None:
        with self._lock:
            self._backend.move_password(old_name, new_name, commit)

    def copy_password(self, source: str, dest: str, commit: bool = True) -> None:
        with self._lock:
            self._backend.copy_password(source, dest, commit)

    # -- syncing -------------------------------------------------------------

    def sync_capability(self) -> SyncCapability:
        """Not serialized; see the module docstring."""
        return self._backend.sync_capability()

    def sync(self) -> SyncResult:
        with self._lock:
            return self._backend.sync()
