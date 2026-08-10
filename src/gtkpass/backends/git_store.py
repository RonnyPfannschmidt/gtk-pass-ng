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
    SUBPROCESS_TIMEOUT_SECONDS,
    GitError,
    SyncCapability,
    SyncNotPermitted,
    SyncResult,
    SyncUnavailable,
)

logger = logging.getLogger(__name__)

#: `user:password@host` in a remote URL. git echoes the URL in its errors, and
#: those errors are shown to the user and written to the log.
_CREDENTIALS = re.compile(r"://[^/@\s]+@")

#: What ssh says when the remote's host key is not in known_hosts, or no longer
#: matches it. Matched on rather than parsed: it is the one failure with a
#: remedy the user has to carry out somewhere else.
_UNKNOWN_HOST_KEY = "Host key verification failed"


def redact(text: str) -> str:
    """Strip credentials out of any URL before the text is shown or logged."""
    return _CREDENTIALS.sub("://", text)


class GitStore:
    """Git operations over one password store directory."""

    def __init__(self, store_dir: Path, git_binary: str, commit_on_write: bool) -> None:
        self.store_dir = store_dir
        self.git_binary = git_binary
        #: The remote's URL, when probe() found one. Only ever used to name the
        #: host in advice; nothing is decided by it.
        self.remote_url: str | None = None
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
        # StrictHostKeyChecking=yes, not accept-new. accept-new takes whatever
        # key answers the first connection from a machine, which is precisely
        # when somebody in the way cannot be detected. What that would cost is
        # not the entries -- they are ciphertext -- but the set of entry names,
        # and the ability to serve an old copy of the store back, restoring a
        # password that was rotated.
        #
        # Batch mode cannot ask, so the first sync on a new machine fails; the
        # remedy is a command, and explain() puts it on screen. Checking a
        # fingerprint against the server is a step worth taking deliberately
        # rather than one to click past.
        env["GIT_SSH_COMMAND"] = "ssh -oBatchMode=yes -oStrictHostKeyChecking=yes"
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
                timeout=SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise GitError(f"git {args[0]} timed out") from error
        except OSError as error:
            raise GitError(f"Could not run git: {error}") from error

        if result.returncode != 0:
            detail = redact(result.stderr.strip() or result.stdout.strip())
            raise GitError(f"git {args[0]} failed: {self.explain(detail)}")
        return result.stdout.strip()

    def explain(self, detail: str) -> str:
        """Add the remedy to a failure that has one somewhere else.

        Only the unknown host key: it is the one thing GTKPass refuses that the
        user is expected to go and resolve, and being strict about it is only
        defensible if what to do about it is on screen.
        """
        if _UNKNOWN_HOST_KEY not in detail:
            return detail

        host = self.ssh_host(self.remote_url or "")
        if host is None:
            return (
                f"{detail}\nThe remote's host key is not one this machine has "
                f"accepted before."
            )
        return (
            f"{detail}\nThe host key for {host} is not one this machine has "
            f"accepted before. Check its fingerprint against the server, then "
            f"connect once with 'ssh {host}' in a terminal, or add it with "
            f"'ssh-keyscan {host} >> ~/.ssh/known_hosts'."
        )

    @staticmethod
    def ssh_host(url: str) -> str | None:
        """The host an ssh remote names, or None when it is not one.

        Only ever used to name it in advice, so an answer it is not sure of is
        worse than none: a wrong hostname sends somebody to check a fingerprint
        that was never in question.
        """
        remainder = url
        if "://" in url:
            scheme, _, remainder = url.partition("://")
            if scheme not in {"ssh", "git+ssh"}:
                return None
        elif ":" not in url or url.startswith("/"):
            # A local path, and scp syntax needs the colon that separates it
            # from the path.
            return None

        _, _, authority = remainder.rpartition("@")
        authority = authority.split("/")[0]
        if authority.startswith("["):
            # A bracketed IPv6 literal, which carries colons of its own.
            address, _, _ = authority.partition("]")
            return address[1:] or None
        host = authority.split(":")[0]
        return host or None

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
        store.remote_url = store._try("remote", "get-url", remote)
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

        # --untracked-files=no: a rebase over modified *tracked* files is what
        # this refuses, and that is what git itself refuses too. A file git
        # never tracked -- an editor backup, a .gpg-id nobody committed -- is
        # not the store's business, and counting it disabled syncing for good
        # while telling the user to discard something they may want kept.
        # An incoming commit that would overwrite one still fails, in git's own
        # words, which name the file.
        if self._run("status", "--porcelain", "--untracked-files=no"):
            raise GitError(
                "The store has uncommitted changes. Commit or discard them "
                "before syncing."
            )

        before = self._revision_count()

        # Fetch before pulling, so what the remote now says can be compared with
        # what it said last time. `pull --rebase` would do the fetch itself and
        # rebase onto the result in the same breath, leaving no moment at which
        # to look. The extra round trip is nearly free: the pull that follows
        # has nothing left to fetch.
        previous = self._try("rev-parse", "@{upstream}")
        self._run("fetch")
        self._refuse_rewritten_history(previous)

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

    def _refuse_rewritten_history(self, previous: str | None) -> None:
        """Stop if the remote no longer contains the commit this store was on.

        A force-push can drop entries, or restore the ciphertext of a password
        that was rotated -- which still decrypts. Rebasing onto that history
        adopts it silently, and a store of ciphertext offers nothing afterwards
        that would look wrong.

        Only history that *disappeared* is refused. A remote that has grown, and
        one that has grown while this store committed as well, are the ordinary
        cases and go through as before.
        """
        if previous is None:
            # Nothing fetched from this remote before, so there is no claim to
            # compare against. The host key is what covers a first connection.
            return

        current = self._try("rev-parse", "@{upstream}")
        if current is None or current == previous:
            return

        # `--is-ancestor` answers by exit status and prints nothing, so the
        # empty string it returns on success is the yes. `is not None` rather
        # than a truth test, which would read every yes as a no.
        if self._try("merge-base", "--is-ancestor", previous, current) is not None:
            return

        raise GitError(
            "Sync stopped: the remote's history no longer contains the commit "
            "this store was last synced with. A rewritten remote can drop "
            "entries, or bring back an old copy of one. Nothing has been "
            "changed here; compare the two with git, and reset this store to "
            "the remote yourself if the rewrite was meant."
        )

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
