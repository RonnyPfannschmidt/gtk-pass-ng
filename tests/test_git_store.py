"""Git over a password store: what it may do, and how it fails.

Everything here runs against a bare repository on disk instead of a network
remote, so push, rebase, conflict and non-fast-forward are all reachable with
nothing listening on a socket. Nothing here needs gpg: the entries are plain
bytes in .gpg files, because GitStore never encrypts and never decrypts. That
separation is the point -- if this behaviour lived inside DirectBackend, the
whole matrix would skip on a machine without a GPG key.
"""

from pathlib import Path

import pytest
from conftest import git, init_repo

from gtkpass.backends import GitError
from gtkpass.backends.git_store import GitStore, SyncUnavailable

pytestmark = pytest.mark.requires_git


def entry(store: Path, name: str, content: bytes = b"\x01ciphertext") -> Path:
    path = store / f"{name}.gpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def open_store(path: Path, commit_on_write: bool = True) -> GitStore:
    store, _ = GitStore.probe(path, commit_on_write=commit_on_write)
    assert store is not None, "expected this store to be syncable"
    return store


class TestWhatCannotSync:
    """Each reason is distinct, because each has a different remedy."""

    def test_a_plain_directory_is_not_a_repository(self, tmp_path):
        store, capability = GitStore.probe(tmp_path, commit_on_write=True)

        assert store is None
        assert capability.reason is SyncUnavailable.NOT_A_REPO
        assert not capability.supported

    def test_a_repository_without_a_remote_cannot_sync(self, store_repo):
        _, capability = GitStore.probe(store_repo, commit_on_write=True)

        assert capability.reason is SyncUnavailable.NO_REMOTE

    def test_a_store_nested_in_a_larger_repository_is_refused(self, tmp_path):
        """Pushing someone's dotfiles because their store lives inside them."""
        outer = init_repo(tmp_path / "dotfiles")
        nested = outer / "passwords"
        nested.mkdir()
        entry(nested, "email")

        _, capability = GitStore.probe(nested, commit_on_write=True)

        assert capability.reason is SyncUnavailable.NESTED_IN_ANOTHER_REPO
        assert "dotfiles" in capability.detail

    def test_a_missing_git_is_reported(self, store_repo, monkeypatch):
        """git is bundled in the Flatpak but absent in plenty of checkouts."""
        monkeypatch.setattr("gtkpass.backends.git_store.shutil.which", lambda _: None)

        _, capability = GitStore.probe(store_repo, commit_on_write=True)

        assert capability.reason is SyncUnavailable.NO_GIT

    def test_a_configured_remote_is_syncable(self, store_repo, bare_remote):
        _, capability = GitStore.probe(store_repo, commit_on_write=True)

        assert capability.supported
        assert capability.remote == "origin"
        assert capability.branch == "main"


class TestFailuresAreLegible:
    def test_a_failing_command_raises(self, store_repo, bare_remote):
        with pytest.raises(GitError):
            open_store(store_repo)._run("checkout", "no-such-branch")

    def test_the_message_carries_what_git_said(self, store_repo, bare_remote):
        """Without this the user gets "git failed" and nothing to act on."""
        with pytest.raises(GitError) as raised:
            open_store(store_repo)._run("checkout", "no-such-branch")

        assert "no-such-branch" in str(raised.value)

    def test_credentials_in_a_remote_url_are_not_echoed(self, store_repo, tmp_path):
        """An https remote can carry a token, and this text reaches a toast."""
        git(
            "remote",
            "add",
            "leaky",
            "https://ronny:sup3rsecret@example.invalid/store.git",
            cwd=store_repo,
        )
        store = GitStore(store_repo, "git", commit_on_write=True)

        with pytest.raises(GitError) as raised:
            store._run("push", "leaky", "main")

        assert "sup3rsecret" not in str(raised.value)
        assert "example.invalid" in str(raised.value)


class TestGitIsNeverAllowedToPrompt:
    """A prompt in a worker thread is a wedged thread, not a question.

    The manager's pool has four workers and shutdown() waits on them from the UI
    thread, so one ssh blocked on a passphrase freezes the window.
    """

    def test_the_terminal_prompt_is_disabled(self, store_repo):
        assert (
            GitStore(store_repo, "git", commit_on_write=True)._env[
                "GIT_TERMINAL_PROMPT"
            ]
            == "0"
        )

    def test_ssh_runs_in_batch_mode(self, store_repo):
        env = GitStore(store_repo, "git", commit_on_write=True)._env

        assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]

    def test_the_askpass_helpers_are_cleared(self, store_repo, monkeypatch):
        monkeypatch.setenv("GIT_ASKPASS", "/usr/bin/some-gui-prompt")
        env = GitStore(store_repo, "git", commit_on_write=True)._env

        assert env["GIT_ASKPASS"] == ""
        assert env["SSH_ASKPASS"] == ""


class TestTheRemoteHasToBeKnownAlready:
    """A store's remote is trusted on the strength of its host key, or not.

    accept-new means the first connection from a machine takes whatever key
    answers. What is at stake is not the entries, which are ciphertext, but the
    set of entry names and the ability to serve an old copy of the store back --
    and the first connection is exactly when somebody in the way is undetectable.
    """

    def test_an_unknown_host_key_is_not_accepted(self, store_repo):
        env = GitStore(store_repo, "git", commit_on_write=True)._env

        assert "StrictHostKeyChecking=yes" in env["GIT_SSH_COMMAND"]
        assert "accept-new" not in env["GIT_SSH_COMMAND"]

    @pytest.mark.parametrize(
        ("url", "host"),
        [
            ("git@github.com:me/store.git", "github.com"),
            ("ssh://git@example.org/srv/store.git", "example.org"),
            ("ssh://git@example.org:2222/srv/store.git", "example.org"),
            ("me@[2001:db8::1]:store.git", "2001:db8::1"),
            ("https://example.org/store.git", None),
            ("/srv/store.git", None),
        ],
    )
    def test_the_host_is_read_out_of_the_remote_url(self, store_repo, url, host):
        """Only to name it in the advice, so a wrong answer must be no answer."""
        assert GitStore.ssh_host(url) == host

    def test_a_rejected_host_key_says_what_to_do(self, store_repo, bare_remote):
        """Strict is only defensible if the way past it is on screen.

        Batch mode cannot ask, so the remedy is a command -- and the fingerprint
        wants checking against the server anyway, which is the step a prompt
        invites people to skip.
        """
        store = open_store(store_repo)
        store.remote_url = "git@example.org:me/store.git"

        explained = store.explain("Host key verification failed.")

        assert "example.org" in explained
        assert "ssh-keyscan" in explained or "ssh " in explained

    def test_anything_else_is_passed_through_unchanged(self, store_repo):
        store = open_store(store_repo)

        assert store.explain("some other failure") == "some other failure"


class TestARewrittenRemoteIsRefused:
    """`pull --rebase` accepts whatever history the remote offers.

    A remote that was force-pushed can drop entries, or restore the ciphertext
    of a password that was rotated -- which still decrypts. Rebasing onto it
    adopts that history without a word, and for a store of ciphertext there is
    nothing on screen afterwards that would look wrong.
    """

    def rewritten(self, store_repo, other_clone, bare_remote):
        """Sync once, then have the remote drop the commit that brought."""
        from conftest import git

        entry(other_clone, "shared")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Add shared", cwd=other_clone)
        git("push", cwd=other_clone)
        open_store(store_repo).sync()

        # The remote loses that commit and gains a different one in its place.
        git("reset", "--hard", "HEAD~1", cwd=other_clone)
        entry(other_clone, "replacement")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Something else entirely", cwd=other_clone)
        git("push", "--force", cwd=other_clone)

    def test_it_is_reported_rather_than_rebased_onto(
        self, store_repo, bare_remote, other_clone
    ):
        self.rewritten(store_repo, other_clone, bare_remote)

        with pytest.raises(GitError, match="no longer contains"):
            open_store(store_repo).sync()

    def test_the_store_is_left_where_it_was(self, store_repo, bare_remote, other_clone):
        from conftest import git

        self.rewritten(store_repo, other_clone, bare_remote)
        before = git("rev-parse", "HEAD", cwd=store_repo)

        with pytest.raises(GitError):
            open_store(store_repo).sync()

        assert git("rev-parse", "HEAD", cwd=store_repo) == before

    def test_an_ordinary_pull_is_not_mistaken_for_one(
        self, store_repo, bare_remote, other_clone
    ):
        """The remote growing is the common case and must stay silent."""
        from conftest import git

        entry(other_clone, "added-elsewhere")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Add one", cwd=other_clone)
        git("push", cwd=other_clone)

        result = open_store(store_repo).sync()

        assert result.pulled == 1

    def test_a_local_commit_alongside_a_remote_one_is_not_one_either(
        self, store_repo, bare_remote, other_clone
    ):
        """Diverged histories rebase, as they did before; nothing was dropped."""
        from conftest import git

        entry(other_clone, "theirs")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Theirs", cwd=other_clone)
        git("push", cwd=other_clone)

        store = open_store(store_repo)
        store.commit([entry(store_repo, "mine")], "Mine")

        result = store.sync()

        assert result.pushed == 1


class TestCommitting:
    def test_a_new_entry_is_committed(self, store_repo):
        store = GitStore(store_repo, "git", commit_on_write=True)
        path = entry(store_repo, "email/work")

        store.commit([path], "Add password for email/work using gtkpass.")

        assert git("status", "--porcelain", cwd=store_repo) == ""
        assert "email/work" in git("log", "-1", "--pretty=%s", cwd=store_repo)

    def test_a_deletion_is_committed(self, store_repo):
        """`git add <path>` alone does not stage a removal; -A does."""
        store = GitStore(store_repo, "git", commit_on_write=True)
        path = entry(store_repo, "email/work")
        store.commit([path], "Add password for email/work using gtkpass.")

        path.unlink()
        store.commit([path], "Remove email/work from store.")

        assert git("status", "--porcelain", cwd=store_repo) == ""
        assert "email/work.gpg" not in git("ls-files", cwd=store_repo)

    def test_nothing_to_commit_is_not_an_error(self, store_repo):
        store = GitStore(store_repo, "git", commit_on_write=True)

        store.commit([store_repo / "absent.gpg"], "Nothing happened.")

    def test_a_backend_that_commits_for_itself_is_left_alone(self, store_repo):
        """pass commits on every write; a second commit would be noise."""
        store = GitStore(store_repo, "git", commit_on_write=False)
        before = git("rev-list", "--count", "HEAD", cwd=store_repo)
        entry(store_repo, "email/work")

        store.commit([store_repo / "email/work.gpg"], "Should not happen.")

        assert git("rev-list", "--count", "HEAD", cwd=store_repo) == before

    def test_the_message_names_the_entry_and_not_its_content(self, store_repo):
        store = GitStore(store_repo, "git", commit_on_write=True)
        path = entry(store_repo, "email/work", b"\x01hunter2-as-ciphertext")

        store.commit([path], "Add password for email/work using gtkpass.")

        message = git("log", "-1", "--pretty=%B", cwd=store_repo)
        assert "email/work" in message
        assert "hunter2" not in message


class TestCommittingNeverAsksForASignature:
    """A store that signs its commits must not make saving a password prompt.

    The commit happens on a worker thread after an entry is written, so a
    pinentry raised there is a dialog nobody asked for in the middle of a save
    -- and where one cannot appear, inside a sandbox without the agent socket
    or on a headless session, it is a worker sitting on a deadline instead.

    GTKPass's commits are bookkeeping: they record that a file changed. They
    are not a claim about who wrote the entry, which is what a signature would
    be asserting.
    """

    @pytest.fixture
    def signing_store(self, store_repo, tmp_path, monkeypatch):
        """A store configured to sign, with no key that could."""
        # Away from the developer's own keyring: nothing here has any business
        # asking gpg-agent about their keys.
        monkeypatch.setenv("GNUPGHOME", str(tmp_path / "gnupg-empty"))
        git("config", "commit.gpgsign", "true", cwd=store_repo)
        git("config", "user.signingkey", "0000000000000000", cwd=store_repo)
        return store_repo

    def test_a_write_is_committed_anyway(self, signing_store):
        store = open_store(signing_store)
        before = git("rev-list", "--count", "HEAD", cwd=signing_store)

        store.commit([entry(signing_store, "email/work")], "Add work")

        assert git("rev-list", "--count", "HEAD", cwd=signing_store) != before

    def test_the_commit_it_made_is_not_signed(self, signing_store):
        store = open_store(signing_store)

        store.commit([entry(signing_store, "email/work")], "Add work")

        # %G? is 'N' for a commit carrying no signature at all.
        assert git("log", "-1", "--pretty=%G?", cwd=signing_store) == "N"


class TestSyncing:
    def test_a_commit_made_elsewhere_is_pulled(
        self, store_repo, bare_remote, other_clone
    ):
        entry(other_clone, "bank/checking")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Add bank/checking", cwd=other_clone)
        git("push", cwd=other_clone)

        open_store(store_repo).sync()

        assert (store_repo / "bank" / "checking.gpg").is_file()

    def test_a_local_commit_is_pushed(self, store_repo, bare_remote):
        store = open_store(store_repo)
        path = entry(store_repo, "email/work")
        store.commit([path], "Add password for email/work using gtkpass.")

        store.sync()

        assert "email/work.gpg" in git(
            "ls-tree", "-r", "--name-only", "main", cwd=bare_remote
        )

    def test_a_divergence_is_rebased_rather_than_merged(
        self, store_repo, bare_remote, other_clone
    ):
        """A merge commit in a password store's history helps nobody."""
        entry(other_clone, "bank/checking")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Add bank/checking", cwd=other_clone)
        git("push", cwd=other_clone)

        store = open_store(store_repo)
        path = entry(store_repo, "email/work")
        store.commit([path], "Add password for email/work using gtkpass.")

        store.sync()

        assert git("rev-list", "--merges", "HEAD", cwd=store_repo) == ""

    def test_it_reports_what_moved(self, store_repo, bare_remote, other_clone):
        entry(other_clone, "bank/checking")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Add bank/checking", cwd=other_clone)
        git("push", cwd=other_clone)

        result = open_store(store_repo).sync()

        assert result.pulled == 1
        assert result.pushed == 0


class TestSyncingRefusesToLeaveAMess:
    def test_a_conflict_leaves_the_store_usable(
        self, store_repo, bare_remote, other_clone
    ):
        """The abort matters: a half-rebased store is one the app cannot read.

        git treats .gpg files as binary and writes no conflict markers, so the
        working file stays whole either way -- but only the abort puts the
        *local* version back and clears the in-progress rebase.
        """
        entry(other_clone, "email/work", b"\x01theirs")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Add email/work", cwd=other_clone)
        git("push", cwd=other_clone)

        store = open_store(store_repo)
        path = entry(store_repo, "email/work", b"\x01ours")
        store.commit([path], "Add password for email/work using gtkpass.")

        with pytest.raises(GitError):
            store.sync()

        assert not (store_repo / ".git" / "rebase-merge").exists()
        assert not (store_repo / ".git" / "rebase-apply").exists()
        assert path.read_bytes() == b"\x01ours"
        assert git("status", "--porcelain", cwd=store_repo) == ""

    def test_a_conflict_says_so(self, store_repo, bare_remote, other_clone):
        entry(other_clone, "email/work", b"\x01theirs")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Add email/work", cwd=other_clone)
        git("push", cwd=other_clone)

        store = open_store(store_repo)
        path = entry(store_repo, "email/work", b"\x01ours")
        store.commit([path], "Add password for email/work using gtkpass.")

        with pytest.raises(GitError) as raised:
            store.sync()

        assert "email/work" in str(raised.value)

    def test_a_modified_entry_is_reported_before_anything_moves(
        self, store_repo, bare_remote
    ):
        """A rebase over a dirty worktree is what this exists to prevent."""
        store = open_store(store_repo)
        store.commit([entry(store_repo, "email/work")], "Add work")
        entry(store_repo, "email/work", content=b"\x01changed")

        with pytest.raises(GitError) as raised:
            store.sync()

        assert "uncommitted" in str(raised.value).lower()

    def test_an_untracked_file_does_not_stop_a_sync(
        self, store_repo, bare_remote, other_clone
    ):
        """git never tracked it, so it is not this store's business.

        A stray editor backup or a .gpg-id nobody committed used to disable the
        sync button permanently, with a message telling the user to commit or
        discard something they may well have wanted left alone.
        """
        from conftest import git

        entry(other_clone, "theirs")
        git("add", "-A", cwd=other_clone)
        git("commit", "-m", "Theirs", cwd=other_clone)
        git("push", cwd=other_clone)
        (store_repo / "notes.txt~").write_text("an editor left this here")

        result = open_store(store_repo).sync()

        assert result.pulled == 1
        assert (store_repo / "notes.txt~").exists(), "the sync took it away"

    def test_an_unreachable_remote_is_reported(self, store_repo, tmp_path):
        git("remote", "add", "origin", str(tmp_path / "nowhere.git"), cwd=store_repo)
        git("config", "branch.main.remote", "origin", cwd=store_repo)
        git("config", "branch.main.merge", "refs/heads/main", cwd=store_repo)

        with pytest.raises(GitError):
            open_store(store_repo).sync()


class TestASandboxThatCannotReadSshConfig:
    """The failure this whole arrangement exists to make legible.

    `~/.ssh/config` is not in the Flatpak manifest, so a remote written against
    a `Host` alias resolves to nothing and ssh reports a hostname that does not
    exist. The remedy is a `flatpak override` the user has to run outside the
    application, which means it has to appear inside it.
    """

    SANDBOXED = """\
[Application]
name=io.github.RonnyPfannschmidt.GTKPass

[Context]
shared=ipc;network;
sockets=gpg-agent;ssh-auth;
filesystems=~/.password-store:create;
"""

    @pytest.fixture
    def sandboxed(self, tmp_path, monkeypatch):
        from gtkpass import sandbox

        info = tmp_path / "flatpak-info"
        info.write_text(self.SANDBOXED)
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", info)
        return info

    @pytest.fixture
    def unsandboxed(self, tmp_path, monkeypatch):
        from gtkpass import sandbox

        monkeypatch.setattr(sandbox, "FLATPAK_INFO", tmp_path / "absent")

    def test_an_unresolved_alias_says_which_override_to_run(
        self, store_repo, sandboxed
    ):
        store = open_store(store_repo)
        store.remote_url = "git@store-host:me/store.git"

        explained = store.explain(
            "ssh: Could not resolve hostname store-host: Name or service not known"
        )

        assert "~/.ssh/config" in explained
        assert "flatpak override --user" in explained
        assert "--filesystem=~/.ssh/config:ro" in explained

    def test_it_says_the_grant_carries_no_key(self, store_repo, sandboxed):
        """Otherwise the advice reads as 'hand your private keys to a sandbox'."""
        store = open_store(store_repo)
        store.remote_url = "git@store-host:me/store.git"

        explained = store.explain("ssh: Could not resolve hostname store-host")

        assert "private key" in explained or "no key" in explained

    def test_outside_a_sandbox_the_advice_is_not_offered(self, store_repo, unsandboxed):
        """There it is a typo or DNS, and GTKPass has nothing to add."""
        store = open_store(store_repo)
        store.remote_url = "git@store-host:me/store.git"
        detail = "ssh: Could not resolve hostname store-host"

        assert store.explain(detail) == detail

    def test_a_granted_config_is_not_advised_again(
        self, store_repo, tmp_path, monkeypatch
    ):
        """Once it is mounted, an unresolved name is the user's own DNS."""
        from gtkpass import sandbox

        info = tmp_path / "flatpak-info"
        info.write_text(
            self.SANDBOXED.replace("filesystems=", "filesystems=~/.ssh/config:ro;")
        )
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", info)
        store = open_store(store_repo)
        detail = "ssh: Could not resolve hostname store-host"

        assert store.explain(detail) == detail

    def test_a_rejected_host_key_in_a_sandbox_says_to_grant_known_hosts(
        self, store_repo, sandboxed
    ):
        """ssh-keyscan on the host cannot help a sandbox that cannot read it.

        The unsandboxed advice is actively misleading here: the user runs it,
        the file changes, and nothing inside the sandbox is any different.
        """
        store = open_store(store_repo)
        store.remote_url = "git@example.org:me/store.git"

        explained = store.explain("Host key verification failed.")

        assert "--filesystem=~/.ssh/known_hosts:ro" in explained

    def test_outside_a_sandbox_the_keyscan_advice_is_unchanged(
        self, store_repo, unsandboxed
    ):
        store = open_store(store_repo)
        store.remote_url = "git@example.org:me/store.git"

        explained = store.explain("Host key verification failed.")

        assert "ssh-keyscan" in explained
        assert "flatpak override" not in explained

    def test_only_the_missing_grant_is_asked_for(
        self, store_repo, tmp_path, monkeypatch
    ):
        """Asking again for something already granted reads as advice that
        did not work."""
        from gtkpass import sandbox

        info = tmp_path / "flatpak-info"
        info.write_text(
            self.SANDBOXED.replace("filesystems=", "filesystems=~/.ssh/config:ro;")
        )
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", info)
        store = open_store(store_repo)
        store.remote_url = "git@example.org:me/store.git"

        explained = store.explain("Host key verification failed.")

        assert "--filesystem=~/.ssh/known_hosts:ro" in explained
        assert "--filesystem=~/.ssh/config:ro" not in explained


class TestAStoreWithNoCommitIdentity:
    """git refuses to commit without one, and says so in a way nobody acts on.

    The message it prints is about `git config --global`, which inside a
    sandbox writes somewhere private to the application -- so the advice is
    not wrong exactly, but it is not the fix either. What is missing is
    usually an identity for this particular store.
    """

    IDENTITY_FAILURE = (
        "Author identity unknown\n\n*** Please tell me who you are.\n\n"
        "fatal: unable to auto-detect email address (got 'user@host.(none)')"
    )

    SANDBOXED = """\
[Application]
name=io.github.RonnyPfannschmidt.GTKPass

[Context]
shared=ipc;
sockets=gpg-agent;
filesystems=~/.password-store:create;xdg-config/git:ro;
"""

    @pytest.fixture
    def unsandboxed(self, tmp_path, monkeypatch):
        from gtkpass import sandbox

        monkeypatch.setattr(sandbox, "FLATPAK_INFO", tmp_path / "absent")

    def sandbox_with(self, tmp_path, monkeypatch, contents):
        from gtkpass import sandbox

        info = tmp_path / "flatpak-info"
        info.write_text(contents)
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", info)

    def test_it_says_how_to_give_the_store_one(self, store_repo, unsandboxed):
        store = open_store(store_repo)

        explained = store.explain(self.IDENTITY_FAILURE)

        assert "user.email" in explained
        assert "git -C" in explained or "config" in explained

    def test_it_names_this_store(self, store_repo, unsandboxed):
        """Advice about `--global` is what git already said and it did not help."""
        store = open_store(store_repo)

        explained = store.explain(self.IDENTITY_FAILURE)

        assert str(store_repo) in explained

    def test_the_granted_sandbox_is_not_told_to_grant_it_again(
        self, store_repo, tmp_path, monkeypatch
    ):
        """The manifest grants it, so a mounted config is the normal case."""
        self.sandbox_with(tmp_path, monkeypatch, self.SANDBOXED)
        store = open_store(store_repo)

        explained = store.explain(self.IDENTITY_FAILURE)

        assert "flatpak override" not in explained

    def test_a_revoked_grant_is_named(self, store_repo, tmp_path, monkeypatch):
        """Someone who took it away with --nofilesystem should learn that."""
        self.sandbox_with(
            tmp_path, monkeypatch, self.SANDBOXED.replace("xdg-config/git:ro;", "")
        )
        store = open_store(store_repo)

        explained = store.explain(self.IDENTITY_FAILURE)

        assert "--filesystem=xdg-config/git:ro" in explained
        assert "flatpak override --user" in explained

    def test_anything_else_is_still_passed_through(self, store_repo, unsandboxed):
        store = open_store(store_repo)

        assert store.explain("some other failure") == "some other failure"
