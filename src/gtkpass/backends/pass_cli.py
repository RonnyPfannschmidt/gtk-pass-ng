"""Pass CLI backend for GTKPass.

Delegates password operations to the `pass` command-line tool, taken from PATH.
The packaged application bundles its own copy, so a sandbox is not a special
case: reaching the host's one would have meant `flatpak-spawn --host`, and the
permission that allows is arbitrary command execution outside the sandbox.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gtkpass.safety import default_store_dir, ensure_store_allowed

from . import (
    BackendError,
    BackendMetadata,
    BackendSettings,
    PasswordBackend,
    PasswordEntry,
    PasswordMetadata,
    SyncCapability,
    SyncResult,
    SyncUnavailable,
)
from .git_store import GitStore


@dataclass
class PassBackendSettings(BackendSettings):
    """Settings for Pass CLI backend.

    Attributes:
        password_store_dir: Optional path to password store
            (None = use $PASSWORD_STORE_DIR or ~/.password-store)
        use_git: Whether to enable git operations (default: True)
    """

    password_store_dir: Path | None = None
    use_git: bool = True


class PassBackend(PasswordBackend):
    """Pass CLI backend.

    Delegates all operations to the standard Unix password manager `pass`.
    Automatically detects flatpak environment and uses `flatpak-spawn --host`
    to invoke the host's pass command.

    This backend is useful when:
    - Running in a flatpak container (uses host's password store)
    - You want to use existing pass scripts and workflows
    - You prefer pass's CLI interface for some operations
    """

    metadata = BackendMetadata(
        id="pass",
        name="Pass CLI",
        icon="network-server-symbolic",
        description="Delegate to pass command",
    )

    def __init__(
        self,
        pass_cmd: list[str],
        env: dict,
        password_store_dir: Path,
        use_git: bool = True,
    ):
        """Initialize Pass backend.

        Args:
            pass_cmd: Command to invoke pass
            env: Environment variables for pass command
            password_store_dir: The store this instance was configured with
            use_git: Whether to offer syncing this store with its remote
        """
        self._pass_cmd = pass_cmd
        self._env = env
        self.password_store_dir = password_store_dir
        # commit_on_write=False, and this is the whole difference from
        # DirectBackend: pass commits by itself on every insert, rm, mv and cp
        # whenever the store is a repository, so a commit from here would add a
        # second, empty one after each write. The GitStore exists for sync()
        # and for answering whether sync is possible.
        self._git, self._sync_capability = GitStore.probe(
            password_store_dir, commit_on_write=False
        )
        if self._sync_capability.supported and not use_git:
            self._sync_capability = SyncCapability.unsupported(
                SyncUnavailable.NOT_OFFERED,
                "Syncing is turned off for this store in its settings.",
            )

    @classmethod
    def is_available(cls) -> bool:
        """Check if Pass backend is available.

        Returns:
            True if the pass command is on PATH
        """
        return shutil.which("pass") is not None

    @classmethod
    def create(cls, settings: PassBackendSettings | None = None) -> "PassBackend":
        """Create and initialize a backend instance.

        Args:
            settings: Pass backend settings (uses defaults if None)

        Returns:
            Initialized backend instance

        Raises:
            BackendError: If backend is not available or initialization fails
        """
        if not cls.is_available():
            raise BackendError(f"{cls.metadata.name} backend is not available")

        if settings is None:
            settings = PassBackendSettings()

        store_dir = settings.password_store_dir or default_store_dir()
        ensure_store_allowed(store_dir)

        # Always the pass on PATH. The packaged application bundles its own, so
        # a sandbox needs no special case; asking the host to run it through
        # `flatpak-spawn --host` would have meant granting arbitrary command
        # execution outside the sandbox, which is the whole sandbox.
        if not shutil.which("pass"):
            raise BackendError("pass command not available")
        pass_cmd = ["pass"]

        # Set up environment for pass command. This is the only thing that
        # tells pass where the store is, so every subprocess has to carry it.
        #
        # settings.use_git deliberately does not appear here. It used to set
        # PASSWORD_STORE_ENABLE_EXTENSIONS, which is the extensions knob and
        # has nothing to do with git, so it never disabled anything. pass
        # decides to commit by whether the store has a .git and there is no
        # environment variable for it; the preference now means "offer to sync
        # this store", which GTKPass reads rather than pass.
        env = os.environ.copy()
        if settings.password_store_dir:
            env["PASSWORD_STORE_DIR"] = str(settings.password_store_dir)

        return cls(
            pass_cmd=pass_cmd,
            env=env,
            password_store_dir=store_dir,
            use_git=settings.use_git,
        )

    # -- syncing -------------------------------------------------------------

    def sync_capability(self) -> SyncCapability:
        return self._sync_capability

    def sync(self) -> SyncResult:
        if self._git is None or not self._sync_capability.supported:
            raise BackendError(self._sync_capability.detail)
        return self._git.sync()

    # -- paths ---------------------------------------------------------------

    def _path_for(self, name: str) -> Path:
        """Resolve an entry name to its file, refusing to escape the store.

        An entry name is a path fragment, and it reaches a subprocess. Without
        this, `../../secrets` addressed whatever sat above the store.
        """
        candidate = (self.password_store_dir / f"{name}.gpg").resolve()
        root = self.password_store_dir.resolve()
        if not candidate.is_relative_to(root):
            raise BackendError(f"'{name}' is outside the password store")
        return candidate

    def _existing(self, name: str) -> Path:
        path = self._path_for(name)
        if not path.is_file():
            raise FileNotFoundError(f"Password '{name}' not found")
        return path

    def _run_pass(
        self, args: list[str], input_data: str | None = None
    ) -> subprocess.CompletedProcess:
        """Run pass command with arguments.

        Args:
            args: Arguments to pass command
            input_data: Optional input data to pass via stdin

        Returns:
            Completed process

        Raises:
            BackendError: If command fails
        """
        cmd = self._pass_cmd + args

        try:
            result = subprocess.run(
                cmd,
                input=input_data,
                capture_output=True,
                text=True,
                check=True,
                env=self._env,
            )
            return result
        except subprocess.CalledProcessError as e:
            raise BackendError(f"pass command failed: {e.stderr}") from e
        except Exception as e:
            raise BackendError(f"Failed to run pass: {e}") from e

    def list_passwords(self, prefix: str = "") -> list[PasswordMetadata]:
        """List the store's entries by reading its directory tree.

        `pass ls` is a user interface, not an integration point. It renders the
        store as `tree` art: box-drawing characters, non-breaking-space indents,
        and nesting expressed as indentation, so `bank/checking` arrives as
        `checking` with no way back to its folder. The parser that tried to
        undo that also skipped every line containing a horizontal rule, which
        is every entry line, so this method returned nothing for any store.

        Entry names are filenames. Reading them needs no GPG and no subprocess,
        so pass keeps the operations that do.
        """
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
        return entries

    def get_password(self, name: str) -> PasswordEntry:
        """Get a specific password entry.

        Args:
            name: Name of the password

        Returns:
            Password entry with content

        Raises:
            FileNotFoundError: If password doesn't exist
            BackendError: If retrieval fails
        """
        path = self._existing(name)
        result = self._run_pass(["show", name])

        return PasswordEntry(
            name=name,
            path=path,
            content=result.stdout.rstrip("\n"),
        )

    def add_password(self, name: str, content: str, commit: bool = True) -> None:
        """Add a new password entry.

        Args:
            name: Name for the password
            content: Password content
            commit: Whether to commit to git (pass handles this automatically)

        Raises:
            FileExistsError: If password already exists
            BackendError: If creation fails
        """
        if self._path_for(name).exists():
            raise FileExistsError(f"Password '{name}' already exists")

        # Through _run_pass, which is the only thing that carries the store
        # location. Calling subprocess.run here directly meant a configured
        # PASSWORD_STORE_DIR was read from but written to ~/.password-store.
        self._run_pass(["insert", "-m", name], input_data=content)

    def edit_password(self, name: str, content: str, commit: bool = True) -> None:
        """Edit an existing password entry.

        Args:
            name: Name of the password to edit
            content: New password content
            commit: Whether to commit to git

        Raises:
            FileNotFoundError: If password doesn't exist
            BackendError: If update fails
        """
        self._existing(name)

        # pass has no edit-in-place command, so this is insert with force.
        # Through _run_pass for the same reason as add_password.
        self._run_pass(["insert", "-m", "-f", name], input_data=content)

    def delete_password(self, name: str, commit: bool = True) -> None:
        """Delete a password entry.

        Args:
            name: Name of the password to delete
            commit: Whether to commit to git

        Raises:
            FileNotFoundError: If password doesn't exist
            BackendError: If deletion fails
        """
        self._existing(name)
        self._run_pass(["rm", "-f", name])

    def move_password(self, old_name: str, new_name: str, commit: bool = True) -> None:
        """Move/rename a password entry.

        Args:
            old_name: Current name of the password
            new_name: New name for the password
            commit: Whether to commit to git

        Raises:
            FileNotFoundError: If old password doesn't exist
            FileExistsError: If new name already exists
            BackendError: If move fails
        """
        self._existing(old_name)
        self._path_for(new_name)

        # pass, not a filesystem move: crossing into a subtree with its own
        # .gpg-id has to re-encrypt to that subtree's recipients.
        self._run_pass(["mv", "-f", old_name, new_name])

    def copy_password(self, source: str, dest: str, commit: bool = True) -> None:
        """Copy a password entry.

        Args:
            source: Name of the password to copy
            dest: Name for the copy
            commit: Whether to commit to git

        Raises:
            FileNotFoundError: If source doesn't exist
            FileExistsError: If destination already exists
            BackendError: If copy fails
        """
        self._existing(source)
        self._path_for(dest)
        self._run_pass(["cp", "-f", source, dest])

    def search(self, query: str) -> list[PasswordMetadata]:
        """Match names only, as DirectBackend does.

        This used to run `pass grep`, which decrypts every entry in the store
        to grep its plaintext: it prompts for the passphrase, prints matching
        lines, and defeats the point of the store being encrypted at rest. It
        also passed a `check` argument _run_pass does not take, so every search
        raised TypeError and the method had never once returned a result.
        """
        lowered = query.lower()
        return [
            entry for entry in self.list_passwords() if lowered in entry.name.lower()
        ]
