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
)


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

    def __init__(self, pass_cmd: list[str], env: dict):
        """Initialize Pass backend.

        Args:
            pass_cmd: Command to invoke pass
            env: Environment variables for pass command
        """
        self._pass_cmd = pass_cmd
        self._env = env

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

        ensure_store_allowed(settings.password_store_dir or default_store_dir())

        # Always the pass on PATH. The packaged application bundles its own, so
        # a sandbox needs no special case; asking the host to run it through
        # `flatpak-spawn --host` would have meant granting arbitrary command
        # execution outside the sandbox, which is the whole sandbox.
        if not shutil.which("pass"):
            raise BackendError("pass command not available")
        pass_cmd = ["pass"]

        # Set up environment for pass command
        env = os.environ.copy()
        if settings.password_store_dir:
            env["PASSWORD_STORE_DIR"] = str(settings.password_store_dir)
        if not settings.use_git:
            env["PASSWORD_STORE_ENABLE_EXTENSIONS"] = "false"

        return cls(pass_cmd=pass_cmd, env=env)

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
        """List all passwords, optionally filtered by prefix.

        Args:
            prefix: Optional prefix to filter results

        Returns:
            List of password metadata
        """
        try:
            result = self._run_pass(["ls", prefix] if prefix else ["ls"])

            passwords = []
            for line in result.stdout.split("\n"):
                line = line.strip()

                # Skip empty lines and tree decoration
                if not line or line.startswith("Password Store") or "──" in line:
                    continue

                # Remove tree characters and .gpg extension
                name = line
                for char in ["├──", "└──", "│", "─", " "]:
                    name = name.replace(char, "")

                if name.endswith(".gpg"):
                    name = name[:-4]

                if name:
                    # Construct path (we don't have actual file access in flatpak)
                    path = Path(f"pass://{name}")
                    passwords.append(
                        PasswordMetadata(
                            name=name,
                            path=path,
                            modified=0.0,  # pass doesn't provide timestamps easily
                        )
                    )

            return sorted(passwords, key=lambda x: x.name)

        except BackendError:
            raise
        except Exception as e:
            raise BackendError(f"Failed to list passwords: {e}") from e

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
        try:
            result = self._run_pass(["show", name])
            content = result.stdout.rstrip("\n")

            return PasswordEntry(
                name=name,
                path=Path(f"pass://{name}"),
                content=content,
            )

        except BackendError as e:
            if "is not in the password store" in str(e):
                raise FileNotFoundError(f"Password '{name}' not found") from e
            raise

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
        try:
            # pass insert uses stdin
            result = subprocess.run(
                [*self._pass_cmd, "insert", "-m", name],
                input=content,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                if "already exists" in result.stderr:
                    raise FileExistsError(f"Password '{name}' already exists")
                raise BackendError(f"Failed to add password: {result.stderr}")

        except (FileExistsError, BackendError):
            raise
        except Exception as e:
            raise BackendError(f"Failed to add password '{name}': {e}") from e

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
        # pass doesn't have a direct edit command, use insert with force
        try:
            result = subprocess.run(
                [*self._pass_cmd, "insert", "-m", "-f", name],
                input=content,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                if "is not in the password store" in result.stderr:
                    raise FileNotFoundError(f"Password '{name}' not found")
                raise BackendError(f"Failed to edit password: {result.stderr}")

        except (FileNotFoundError, BackendError):
            raise
        except Exception as e:
            raise BackendError(f"Failed to edit password '{name}': {e}") from e

    def delete_password(self, name: str, commit: bool = True) -> None:
        """Delete a password entry.

        Args:
            name: Name of the password to delete
            commit: Whether to commit to git

        Raises:
            FileNotFoundError: If password doesn't exist
            BackendError: If deletion fails
        """
        try:
            result = self._run_pass(["rm", "-f", name])

            if "is not in the password store" in result.stderr:
                raise FileNotFoundError(f"Password '{name}' not found")

        except (FileNotFoundError, BackendError):
            raise
        except Exception as e:
            raise BackendError(f"Failed to delete password '{name}': {e}") from e

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
        try:
            result = self._run_pass(["mv", "-f", old_name, new_name])

            if "is not in the password store" in result.stderr:
                raise FileNotFoundError(f"Password '{old_name}' not found")

        except (FileNotFoundError, BackendError):
            raise
        except Exception as e:
            raise BackendError(f"Failed to move password: {e}") from e

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
        try:
            result = self._run_pass(["cp", "-f", source, dest])

            if "is not in the password store" in result.stderr:
                raise FileNotFoundError(f"Password '{source}' not found")

        except (FileNotFoundError, BackendError):
            raise
        except Exception as e:
            raise BackendError(f"Failed to copy password: {e}") from e

    def search(self, query: str) -> list[PasswordMetadata]:
        """Search for passwords matching query.

        Args:
            query: Search query

        Returns:
            List of matching password metadata entries
        """
        try:
            result = self._run_pass(["grep", "-l", query], check=False)

            passwords = []
            for line in result.stdout.split("\n"):
                name = line.strip()
                if name:
                    passwords.append(
                        PasswordMetadata(
                            name=name,
                            path=Path(f"pass://{name}"),
                            modified=0.0,
                        )
                    )

            return sorted(passwords, key=lambda x: x.name)

        except Exception as e:
            raise BackendError(f"Search failed: {e}") from e
