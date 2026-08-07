"""Git over a password store.

The sole owner of every ``git`` subprocess in GTKPass, and deliberately a plain
object rather than a mixin on ``PasswordBackend``: it can then be exercised with
no GPG key, no ``pass`` binary and no backend at all, which is what keeps the
failure-mode tests running on machines that have no key to generate.

**It does not encrypt, and must not.** Encryption stays in
``DirectBackend._encrypt_to_file`` and in ``pass insert``. By the time anything
here runs, the store already holds ``.gpg`` ciphertext; the inputs are file paths
and a commit message. Nothing in this module ever holds a decrypted value.

What does reach a remote is the ciphertext plus the entry *names*, as paths in
the tree and in commit messages -- exactly what ``pass git push`` already sends,
since the names are the filenames. Two consequences worth knowing rather than
working around: git history keeps the ciphertext of deleted entries, and a
remote learns the set of entry names. Both are inherent to a git-backed store.
"""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from gtkpass import sandbox

from . import (
    GitError,
    SyncCapability,
    SyncNotPermitted,
    SyncResult,
    SyncUnavailable,
)

logger = logging.getLogger(__name__)

#: No git operation here is interactive, so anything that has not finished by
#: now is stuck. The manager's pool has four workers and shutdown() waits on
#: them from the UI thread, so a stuck one freezes the window.
TIMEOUT_SECONDS = 120

#: `user:password@host` in a remote URL. git echoes the URL in its errors, and
#: those errors are shown to the user and written to the log.
_CREDENTIALS = re.compile(r"://[^/@\s]+@")


def redact(text: str) -> str:
    """Strip credentials out of any URL before the text is shown or logged."""
    return _CREDENTIALS.sub("://", text)


class GitStore:
    """Git operations over one password store directory."""

    def __init__(self, store_dir: Path, git_binary: str, commit_on_write: bool) -> None:
        self.store_dir = store_dir
        self.git_binary = git_binary
        #: False for backends that commit their own writes -- pass does, on
        #: every insert, rm, mv and cp -- so commit() is a no-op for them.
        self.commit_on_write = commit_on_write
        self._env = self._build_env()

    @staticmethod
    def _build_env() -> dict[str, str]:
        """An environment in which git cannot stop and ask a question.

        Not a hardening nicety. A prompt in a worker thread never gets an
        answer, so the thread never returns, and the pool it came from is
        joined on the UI thread at shutdown.
        """
        env = os.environ.copy()
        # git speaks the user's language otherwise, and this machine's git
        # answers in German. Every decision made from git's output -- and every
        # message shown to the user, since the interface is English throughout
        # -- has to be independent of that.
        env["LC_ALL"] = "C"
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = ""
        env["SSH_ASKPASS"] = ""
        env["GIT_SSH_COMMAND"] = (
            "ssh -oBatchMode=yes -oStrictHostKeyChecking=accept-new"
        )
        return env

    # -- running git ---------------------------------------------------------

    def _run(self, *args: str) -> str:
        """Run one git command, raising GitError with what git said.

        check=False rather than check=True: str(CalledProcessError) does not
        include stderr, which is the only part worth showing anyone.
        """
        try:
            result = subprocess.run(
                [self.git_binary, "-C", str(self.store_dir), *args],
                capture_output=True,
                text=True,
                check=False,
                env=self._env,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise GitError(f"git {args[0]} timed out") from error
        except OSError as error:
            raise GitError(f"Could not run git: {error}") from error

        if result.returncode != 0:
            detail = redact(result.stderr.strip() or result.stdout.strip())
            raise GitError(f"git {args[0]} failed: {detail}")
        return result.stdout.strip()

    def _try(self, *args: str) -> str | None:
        """Run a command whose failure is an answer rather than a problem."""
        try:
            return self._run(*args)
        except GitError:
            return None

    # -- discovery -----------------------------------------------------------

    @classmethod
    def probe(
        cls, store_dir: Path | None, *, commit_on_write: bool
    ) -> tuple["GitStore | None", SyncCapability]:
        """Decide whether this store can sync, cheaply and without hanging.

        Three local commands, no network. Called once on a worker after the
        backends load, never during window construction.
        """
        if store_dir is None:
            return None, SyncCapability.unsupported(
                SyncUnavailable.NO_STORE, "This backend has no password store."
            )

        git_binary = shutil.which("git")
        if git_binary is None:
            return None, SyncCapability.unsupported(
                SyncUnavailable.NO_GIT, "Git is not installed."
            )

        store = cls(store_dir, git_binary, commit_on_write)

        # --show-toplevel rather than testing for a .git directory, so worktrees
        # and submodules answer correctly.
        toplevel = store._try("rev-parse", "--show-toplevel")
        if toplevel is None:
            return None, SyncCapability.unsupported(
                SyncUnavailable.NOT_A_REPO,
                "This store is not a git repository.",
            )

        if Path(toplevel).resolve() != store_dir.resolve():
            return None, SyncCapability.unsupported(
                SyncUnavailable.NESTED_IN_ANOTHER_REPO,
                f"This store sits inside the repository at {toplevel}, "
                "so syncing it would push unrelated work.",
            )

        remotes = store._try("remote")
        if not remotes:
            # Still a repository, so it can be committed to; it just has
            # nowhere to sync with.
            return store, SyncCapability.unsupported(
                SyncUnavailable.NO_REMOTE,
                "No remote is configured for this store.",
            )

        remote = remotes.splitlines()[0]
        branch = store._try("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
        return store, SyncCapability(
            supported=True,
            reason=SyncUnavailable.READY,
            detail=f"Sync with {remote}/{branch}",
            remote=remote,
            branch=branch,
        )

    # -- writing -------------------------------------------------------------

    def commit(self, paths: list[Path], message: str) -> None:
        """Stage the given paths and commit them.

        `git add -A --` rather than a plain add: a delete or a move has to stage
        a removal, and a plain `git add <path>` silently does not.
        """
        if not self.commit_on_write:
            return

        pathspec = [str(path) for path in paths]
        if not self._matches_anything(pathspec):
            # `git add` fails outright on a pathspec matching neither the
            # worktree nor the index, and asking first is cheaper than reading
            # the error -- which arrives in whatever language git is set to.
            return

        self._run("add", "-A", "--", *pathspec)

        if not self._staged_anything():
            # Writing the same content twice stages nothing, and that is not an
            # error worth interrupting a save for.
            return
        self._run("commit", "-m", message)

    def _staged_anything(self) -> bool:
        """`diff --cached --quiet` exits non-zero when something is staged."""
        return self._try("diff", "--cached", "--quiet") is None

    def _matches_anything(self, pathspec: list[str]) -> bool:
        """Whether any of these paths is in the worktree or already tracked.

        A deleted entry is gone from the worktree but still in the index, which
        is exactly the case that has to keep working.
        """
        if any(Path(path).exists() for path in pathspec):
            return True
        return bool(self._try("ls-files", "--", *pathspec))

    # -- syncing -------------------------------------------------------------

    def sync(self) -> SyncResult:
        """Pull with rebase, then push.

        Refuses before starting when the sandbox has not been given the
        permissions this needs, so nothing can block waiting for a socket that
        was never mounted.
        """
        missing = sandbox.missing_sync_permissions()
        if missing:
            raise SyncNotPermitted(
                "Syncing needs permissions this application was not granted: "
                + ", ".join(missing),
                sandbox.override_command(),
            )

        if self._run("status", "--porcelain"):
            raise GitError(
                "The store has uncommitted changes. Commit or discard them "
                "before syncing."
            )

        before = self._revision_count()

        try:
            self._run("pull", "--rebase", "--no-autostash")
        except GitError as error:
            # Leave no rebase in progress: a store stopped mid-rebase is one
            # the application cannot list, and the user did not ask for that.
            if self._rebase_in_progress():
                # Name the entries before aborting; afterwards there is nothing
                # left to ask, and the message degrades to "an entry".
                detail = self._conflict_detail()
                self._try("rebase", "--abort")
                raise GitError(
                    f"Sync stopped: {detail} changed both here and on the "
                    "remote. Resolve it with git and try again."
                ) from error
            raise

        pulled = self._revision_count() - before
        pushed = self._commits_ahead()

        if pushed:
            self._run("push")

        return SyncResult(pulled=pulled, pushed=pushed)

    def _commits_ahead(self) -> int:
        """Local commits the remote does not have yet.

        Nothing to push is the common case -- most syncs only pull -- and
        pushing anyway would reach the network for no reason.
        """
        ahead = self._try("log", "@{upstream}..HEAD", "--pretty=%H")
        if ahead is None:
            return 0
        return len([line for line in ahead.splitlines() if line])

    def _revision_count(self) -> int:
        return int(self._try("rev-list", "--count", "HEAD") or 0)

    def _rebase_in_progress(self) -> bool:
        git_dir = self.store_dir / ".git"
        return (git_dir / "rebase-merge").exists() or (
            git_dir / "rebase-apply"
        ).exists()

    def _conflict_detail(self) -> str:
        """Name the conflicting entries, which are already on screen anyway."""
        conflicted = self._try("diff", "--name-only", "--diff-filter=U") or ""
        names = [
            line[: -len(".gpg")] if line.endswith(".gpg") else line
            for line in conflicted.splitlines()
            if line
        ]
        return ", ".join(names) if names else "an entry"
