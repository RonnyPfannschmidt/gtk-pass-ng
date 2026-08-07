"""How the Pass backend invokes pass, inside a sandbox and outside one.

The packaged application bundles pass itself, so there is one answer in both
places: run it from PATH. The alternative -- asking the host to run it through
`flatpak-spawn --host` -- needs a permission that hands the application
arbitrary command execution outside the sandbox, which is not a trade a
password manager should make.
"""

import shutil
import subprocess

import pytest

from gtkpass.backends import BackendError, SyncUnavailable
from gtkpass.backends.pass_cli import PassBackend, PassBackendSettings


@pytest.fixture
def store(tmp_path):
    """A scratch store, so the guard has nothing to object to."""
    path = tmp_path / "store"
    path.mkdir()
    return path


@pytest.fixture
def recorded_runs(monkeypatch):
    """Capture every `pass` invocation, without running one.

    The backend has more than one call site, and the bug this exists to catch is
    one of them passing a different environment than the others.

    Only pass is intercepted. `pass_cli.subprocess` is the subprocess module
    itself, so a blanket replacement also swallowed the git commands GitStore
    runs while probing the store -- which both hid real behaviour and put
    unrelated entries in this list.
    """
    calls = []
    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        if not cmd or "pass" not in str(cmd[0]):
            return real_run(cmd, **kwargs)
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("gtkpass.backends.pass_cli.subprocess.run", fake_run)
    return calls


@pytest.fixture
def pass_on_path(monkeypatch):
    """Pretend pass is installed, and tell the truth about everything else.

    `pass_cli.shutil` is the shutil module itself, so patching `which` through
    it replaces it for every importer -- including GitStore, which asks the same
    question about git. Answering None for git there made a git-backed store
    report itself unsyncable for a reason that had nothing to do with the test.
    """
    real_which = shutil.which
    monkeypatch.setattr(
        "gtkpass.backends.pass_cli.shutil.which",
        lambda command: "/usr/bin/pass" if command == "pass" else real_which(command),
    )


@pytest.fixture
def no_pass(monkeypatch):
    monkeypatch.setattr("gtkpass.backends.pass_cli.shutil.which", lambda _: None)


@pytest.fixture
def inside_a_flatpak(monkeypatch):
    """Whatever the backend might check, it must see a sandbox.

    Only /.flatpak-info is answered differently; everything else keeps working,
    because os.path.exists is used by half the standard library.
    """
    import os

    real_exists = os.path.exists
    monkeypatch.setattr(
        "gtkpass.backends.pass_cli.os.path.exists",
        lambda path: path == "/.flatpak-info" or real_exists(path),
    )


class TestAvailability:
    def test_pass_on_the_path_is_enough(self, pass_on_path):
        assert PassBackend.is_available()

    def test_without_pass_it_is_unavailable(self, no_pass):
        assert not PassBackend.is_available()

    def test_a_sandbox_changes_nothing(self, pass_on_path, inside_a_flatpak):
        """The bundled pass is on PATH inside the sandbox too."""
        assert PassBackend.is_available()


class TestInvocation:
    def create(self, store):
        return PassBackend.create(PassBackendSettings(password_store_dir=store))

    def test_it_runs_pass_from_the_path(self, pass_on_path, store):
        assert self.create(store)._pass_cmd == ["pass"]

    def test_it_does_not_reach_out_to_the_host_from_a_sandbox(
        self, pass_on_path, inside_a_flatpak, store
    ):
        """flatpak-spawn --host would run commands outside the sandbox."""
        command = self.create(store)._pass_cmd

        assert "flatpak-spawn" not in command
        assert command == ["pass"]

    def test_a_missing_pass_is_reported(self, no_pass, store):
        with pytest.raises(BackendError):
            self.create(store)

    def test_the_configured_store_is_passed_through(self, pass_on_path, store):
        """pass reads the location from the environment, not an argument."""
        assert self.create(store)._env["PASSWORD_STORE_DIR"] == str(store)


class TestEveryCallSeesTheConfiguredStore:
    """pass locates the store from the environment and nothing else.

    A call site that forgets `env=` does not fail; it silently reads and writes
    ~/.password-store instead. That is data loss for anyone with a store
    elsewhere, and it steps around the safety.py guard, which only ever saw the
    path that was configured.
    """

    def create(self, store):
        return PassBackend.create(PassBackendSettings(password_store_dir=store))

    def test_adding_writes_to_the_configured_store(
        self, pass_on_path, store, recorded_runs
    ):
        backend = self.create(store)

        backend.add_password("email/work", "secret")

        _, kwargs = recorded_runs[-1]
        assert kwargs["env"]["PASSWORD_STORE_DIR"] == str(store)

    def test_editing_writes_to_the_configured_store(
        self, pass_on_path, store, recorded_runs
    ):
        (store / "email").mkdir()
        (store / "email" / "work.gpg").write_bytes(b"\x01ciphertext")
        backend = self.create(store)

        backend.edit_password("email/work", "secret")

        _, kwargs = recorded_runs[-1]
        assert kwargs["env"]["PASSWORD_STORE_DIR"] == str(store)

    def test_no_call_site_is_left_without_an_environment(
        self, pass_on_path, store, recorded_runs
    ):
        (store / "a.gpg").write_bytes(b"\x01ciphertext")
        backend = self.create(store)

        backend.add_password("new", "x")
        backend.edit_password("a", "y")
        backend.delete_password("a")
        backend.move_password("a", "b")
        backend.copy_password("a", "c")

        assert recorded_runs, "nothing ran, so this proves nothing"
        for cmd, kwargs in recorded_runs:
            assert kwargs.get("env") is backend._env, f"{cmd} ran without the store"


class TestListing:
    """Listing reads the store layout; it does not parse `pass ls`.

    `pass ls` renders the store as `tree` art. Its output is decorated with box
    characters, indented with non-breaking spaces, and -- fatally -- expresses
    nesting as indentation, so `bank/checking` arrives as `checking` with no way
    back to its folder. The parser that tried also skipped every line
    containing a horizontal rule, which is every entry line, so this backend
    listed nothing at all for any store.

    Entry names are filenames. Reading them needs no GPG and no subprocess, so
    pass is left to do the part that does.
    """

    def create(self, store):
        return PassBackend.create(PassBackendSettings(password_store_dir=store))

    @pytest.fixture
    def populated(self, store):
        (store / "bank").mkdir()
        (store / "bank" / "checking.gpg").write_bytes(b"\x01ciphertext")
        (store / "email").mkdir()
        (store / "email" / "work.gpg").write_bytes(b"\x01ciphertext")
        (store / "loose.gpg").write_bytes(b"\x01ciphertext")
        return store

    def test_it_finds_the_entries(self, pass_on_path, populated):
        names = {e.name for e in self.create(populated).list_passwords()}

        assert names == {"bank/checking", "email/work", "loose"}

    def test_a_nested_entry_keeps_its_folder(self, pass_on_path, populated):
        names = [e.name for e in self.create(populated).list_passwords()]

        assert "bank/checking" in names
        assert "checking" not in names

    def test_names_carry_no_tree_decoration(self, pass_on_path, populated):
        for entry in self.create(populated).list_passwords():
            assert "\xa0" not in entry.name
            assert not set(entry.name) & set("├└│─")

    def test_repository_internals_are_skipped(self, pass_on_path, populated):
        """A .git directory holds .gpg objects of its own."""
        objects = populated / ".git" / "objects"
        objects.mkdir(parents=True)
        (objects / "deadbeef.gpg").write_bytes(b"\x01not an entry")

        names = {e.name for e in self.create(populated).list_passwords()}

        assert names == {"bank/checking", "email/work", "loose"}

    def test_a_prefix_narrows_the_listing(self, pass_on_path, populated):
        entries = self.create(populated).list_passwords("bank")

        assert [e.name for e in entries] == ["bank/checking"]

    def test_listing_runs_no_subprocess(self, pass_on_path, populated, recorded_runs):
        """No GPG is involved in reading filenames, so nothing needs to run."""
        self.create(populated).list_passwords()

        assert recorded_runs == []


class TestExistenceComesFromTheStore:
    """Whether an entry exists is a question about a file, not about pass.

    It used to be answered by matching "is not in the password store" against
    stderr, which only works once pass has already run, and reports nothing at
    all when the message changes. The file is right there.
    """

    def create(self, store):
        return PassBackend.create(PassBackendSettings(password_store_dir=store))

    @pytest.fixture
    def populated(self, store):
        (store / "email").mkdir()
        (store / "email" / "work.gpg").write_bytes(b"\x01ciphertext")
        return store

    def test_reading_a_missing_entry_is_reported(
        self, pass_on_path, populated, recorded_runs
    ):
        with pytest.raises(FileNotFoundError):
            self.create(populated).get_password("email/nonexistent")

        assert recorded_runs == [], "pass ran for an entry that is not there"

    def test_adding_over_an_existing_entry_is_refused(
        self, pass_on_path, populated, recorded_runs
    ):
        with pytest.raises(FileExistsError):
            self.create(populated).add_password("email/work", "secret")

        assert recorded_runs == []

    def test_editing_a_missing_entry_is_reported(
        self, pass_on_path, populated, recorded_runs
    ):
        with pytest.raises(FileNotFoundError):
            self.create(populated).edit_password("email/nope", "secret")

        assert recorded_runs == []

    def test_deleting_a_missing_entry_is_reported(
        self, pass_on_path, populated, recorded_runs
    ):
        with pytest.raises(FileNotFoundError):
            self.create(populated).delete_password("email/nope")

        assert recorded_runs == []

    def test_moving_a_missing_entry_is_reported(
        self, pass_on_path, populated, recorded_runs
    ):
        with pytest.raises(FileNotFoundError):
            self.create(populated).move_password("email/nope", "email/other")

        assert recorded_runs == []

    def test_copying_a_missing_entry_is_reported(
        self, pass_on_path, populated, recorded_runs
    ):
        with pytest.raises(FileNotFoundError):
            self.create(populated).copy_password("email/nope", "email/other")

        assert recorded_runs == []


class TestNamesCannotEscapeTheStore:
    """An entry name is a path fragment, and pass would follow it out.

    DirectBackend refuses this; this backend handed the name straight to a
    subprocess, so `../../` reached whatever was above the store.
    """

    def create(self, store):
        return PassBackend.create(PassBackendSettings(password_store_dir=store))

    @pytest.mark.parametrize(
        "name", ["../outside", "email/../../outside", "/etc/passwd"]
    )
    def test_a_name_leaving_the_store_is_refused(
        self, pass_on_path, store, recorded_runs, name
    ):
        with pytest.raises(BackendError):
            self.create(store).get_password(name)

        assert recorded_runs == []


class TestSearchMatchesNames:
    """Search must not decrypt.

    `pass grep` decrypts every entry in the store to grep its plaintext, which
    prompts for the passphrase and prints matching lines. DirectBackend.search
    already refuses to do that for the stated reason that it defeats the point
    of the store being encrypted at rest; this backend has to agree.
    """

    def create(self, store):
        return PassBackend.create(PassBackendSettings(password_store_dir=store))

    @pytest.fixture
    def populated(self, store):
        (store / "email").mkdir()
        (store / "email" / "work.gpg").write_bytes(b"\x01ciphertext")
        (store / "bank.gpg").write_bytes(b"\x01ciphertext")
        return store

    def test_it_finds_a_matching_name(self, pass_on_path, populated):
        found = [e.name for e in self.create(populated).search("work")]

        assert found == ["email/work"]

    def test_it_is_case_insensitive(self, pass_on_path, populated):
        found = [e.name for e in self.create(populated).search("WORK")]

        assert found == ["email/work"]

    def test_a_miss_returns_nothing(self, pass_on_path, populated):
        assert self.create(populated).search("nothing-like-this") == []

    def test_it_never_runs_pass_grep(self, pass_on_path, populated, recorded_runs):
        self.create(populated).search("work")

        assert recorded_runs == []


class TestGitIsNotAnEnvironmentSetting:
    """pass decides to commit by whether the store has a .git, and nothing else.

    PASSWORD_STORE_ENABLE_EXTENSIONS controls extensions, not git, so setting
    it here never disabled anything. The preference now means "offer to sync
    this store", which is a GTKPass concern rather than a pass one.
    """

    def test_the_extensions_knob_is_not_touched(self, pass_on_path, store):
        backend = PassBackend.create(
            PassBackendSettings(password_store_dir=store, use_git=False)
        )

        assert "PASSWORD_STORE_ENABLE_EXTENSIONS" not in backend._env


@pytest.mark.requires_git
@pytest.mark.requires_pass
@pytest.mark.requires_gpg
class TestPassCommitsForItself:
    """pass commits on every write, so GTKPass must not commit again.

    A second commit per write would double the store's history and produce an
    empty commit each time, since pass has already staged and committed
    everything by the time control returns.
    """

    @pytest.fixture
    def git_store(self, tmp_path):
        from conftest import git, init_repo

        if shutil.which("pass") is None or shutil.which("gpg") is None:
            pytest.skip("pass and gpg are both needed")

        root = init_repo(tmp_path / "store")
        git("add", "-A", cwd=root)
        return root

    def test_the_backend_adds_no_commit_of_its_own(self, git_store):
        """The GitStore is built not to commit; this proves the wiring."""
        backend = PassBackend.create(PassBackendSettings(password_store_dir=git_store))

        assert backend._git is not None
        assert backend._git.commit_on_write is False

    def test_a_commit_from_the_backend_is_a_no_op(self, git_store):
        from conftest import git

        backend = PassBackend.create(PassBackendSettings(password_store_dir=git_store))
        assert backend._git is not None
        before = git("rev-list", "--count", "HEAD", cwd=git_store)
        (git_store / "email.gpg").write_bytes(b"\x01ciphertext")

        backend._git.commit([git_store / "email.gpg"], "Should not happen.")

        assert git("rev-list", "--count", "HEAD", cwd=git_store) == before


@pytest.mark.requires_git
class TestSyncIsOfferedForAGitBackedStore:
    @pytest.fixture
    def git_store(self, tmp_path):
        from conftest import git, init_repo

        root = init_repo(tmp_path / "store")
        remote = tmp_path / "remote.git"
        remote.mkdir()
        git("init", "--bare", "-b", "main", cwd=remote)
        git("remote", "add", "origin", str(remote), cwd=root)
        git("push", "-u", "origin", "main", cwd=root)
        return root

    def test_it_is_offered(self, pass_on_path, git_store):
        backend = PassBackend.create(PassBackendSettings(password_store_dir=git_store))

        assert backend.sync_capability().supported

    def test_turning_git_off_withdraws_the_offer(self, pass_on_path, git_store):
        """The `use-git` preference used to set an unrelated pass variable."""
        backend = PassBackend.create(
            PassBackendSettings(password_store_dir=git_store, use_git=False)
        )

        capability = backend.sync_capability()

        assert not capability.supported
        assert capability.reason is SyncUnavailable.NOT_OFFERED

    def test_a_store_without_a_remote_is_not_offered(self, pass_on_path, store):
        backend = PassBackend.create(PassBackendSettings(password_store_dir=store))

        assert not backend.sync_capability().supported
