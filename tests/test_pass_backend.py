"""How the Pass backend invokes pass, inside a sandbox and outside one.

The packaged application bundles pass itself, so there is one answer in both
places: run it from PATH. The alternative -- asking the host to run it through
`flatpak-spawn --host` -- needs a permission that hands the application
arbitrary command execution outside the sandbox, which is not a trade a
password manager should make.
"""

import os
import shutil
import subprocess
import time

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


class TestAnEntryNameIsNeverReadAsAnOption:
    """An entry name reaches pass in argument position, where getopt reads it.

    Names come out of the store as filenames, and a store can come from a
    remote: `-c.gpg` is a legal file for anyone who can write to one. `pass show
    -c` then copies the entry to the system clipboard -- with none of the
    timeout or the toast GTKPass puts around a copy -- and prints nothing, so
    the entry silently reads as empty. `pass rm -f -r` is a question about
    recursion. Terminating the options is the whole fix, and it has to be at
    every call site rather than the one that motivated it.

    pass consumes `--` in show, insert, delete and copy_move, which is all four
    of the subcommands used here.
    """

    def create(self, store):
        return PassBackend.create(PassBackendSettings(password_store_dir=store))

    @pytest.fixture
    def populated(self, store):
        (store / "-c.gpg").write_bytes(b"\x01ciphertext")
        return store

    def names_in(self, cmd):
        """Everything pass will read as a path rather than as a flag."""
        assert "--" in cmd, f"{cmd} leaves the name where getopt can reach it"
        return cmd[cmd.index("--") + 1 :]

    def test_reading(self, pass_on_path, populated, recorded_runs):
        self.create(populated).get_password("-c")

        assert self.names_in(recorded_runs[-1][0]) == ["-c"]

    def test_adding(self, pass_on_path, store, recorded_runs):
        self.create(store).add_password("-c", "secret")

        assert self.names_in(recorded_runs[-1][0]) == ["-c"]

    def test_editing(self, pass_on_path, populated, recorded_runs):
        self.create(populated).edit_password("-c", "secret")

        assert self.names_in(recorded_runs[-1][0]) == ["-c"]

    def test_deleting(self, pass_on_path, populated, recorded_runs):
        self.create(populated).delete_password("-c")

        assert self.names_in(recorded_runs[-1][0]) == ["-c"]

    def test_moving(self, pass_on_path, populated, recorded_runs):
        self.create(populated).move_password("-c", "-r")

        assert self.names_in(recorded_runs[-1][0]) == ["-c", "-r"]

    def test_copying(self, pass_on_path, populated, recorded_runs):
        self.create(populated).copy_password("-c", "-r")

        assert self.names_in(recorded_runs[-1][0]) == ["-c", "-r"]

    def test_an_ordinary_name_is_terminated_too(
        self, pass_on_path, populated, recorded_runs
    ):
        """No conditional escaping: it either always happens or it is forgotten."""
        (populated / "email").mkdir()
        (populated / "email" / "work.gpg").write_bytes(b"\x01ciphertext")

        self.create(populated).get_password("email/work")

        assert self.names_in(recorded_runs[-1][0]) == ["email/work"]


class TestEncryptingDoesNotConsultTheWebOfTrust:
    """The recipients in .gpg-id are the decision; ownertrust is not.

    Reported from the Flatpak: adding or editing an entry failed, and the
    message was cropped to one line so there was nothing to go on. What gpg was
    actually saying was::

        gpg: <key>: There is no assurance this key belongs to the named user
        gpg: [stdin]: encryption failed: Unusable public key

    The sandbox is granted the public keyring read-only and nothing else, so
    gpg finds no trustdb, builds an empty one, and every recipient in it is
    unknown -- at which point it refuses to encrypt to any of them.

    Whether a key is trusted is not the question a password store asks. The
    question is whether .gpg-id names who it should, and GTKPass answers that
    separately: backends/recipients.py refuses to write at all when that file
    has changed without review. DirectBackend has passed always_trust since it
    was written; this is pass being brought into line with it, so that two
    backends over the same store stop behaving differently.
    """

    def create(self, store):
        return PassBackend.create(PassBackendSettings(password_store_dir=store))

    def test_pass_is_told_not_to_require_ownertrust(self, pass_on_path, store):
        backend = self.create(store)

        assert "--trust-model=always" in backend._env["PASSWORD_STORE_GPG_OPTS"]

    def test_every_call_carries_it(self, pass_on_path, store, recorded_runs):
        """It is the environment pass reads, so it applies to insert and mv alike."""
        backend = self.create(store)
        (store / "a.gpg").write_bytes(b"\x01ciphertext")

        backend.add_password("new", "x")
        backend.edit_password("a", "y")
        backend.move_password("a", "b")

        assert recorded_runs, "nothing ran, so this proves nothing"
        for cmd, kwargs in recorded_runs:
            assert "--trust-model=always" in kwargs["env"]["PASSWORD_STORE_GPG_OPTS"], (
                f"{cmd} would ask gpg to consult the web of trust"
            )

    def test_options_the_user_already_set_are_kept(
        self, pass_on_path, store, monkeypatch
    ):
        """PASSWORD_STORE_GPG_OPTS is the user's variable before it is ours.

        Overwriting it would silently drop whatever they had configured -- a
        keyserver, a cipher preference, --no-encrypt-to.
        """
        monkeypatch.setenv("PASSWORD_STORE_GPG_OPTS", "--compress-algo=none")

        backend = self.create(store)

        options = backend._env["PASSWORD_STORE_GPG_OPTS"]
        assert "--compress-algo=none" in options
        assert "--trust-model=always" in options

    def test_a_trust_model_the_user_chose_is_left_alone(
        self, pass_on_path, store, monkeypatch
    ):
        """Somebody who set one meant it, and two would contradict each other."""
        monkeypatch.setenv("PASSWORD_STORE_GPG_OPTS", "--trust-model=tofu")

        backend = self.create(store)

        assert backend._env["PASSWORD_STORE_GPG_OPTS"] == "--trust-model=tofu"


class TestMovingAFolder:
    """One `pass mv` per entry, not one for the directory.

    `pass mv work archive` is `mv` semantics: whether it renames the folder or
    moves it *inside* an existing one depends on whether the destination is
    already a directory. That is two different results from one request, and
    the answer depends on the state of the store rather than on what was asked
    -- so the entries are moved individually, where the destination path is
    written out in full and there is nothing to interpret.

    pass still does the work per entry: it re-encrypts when the destination
    subtree has a .gpg-id of its own, which a filesystem move would not.
    """

    def create(self, store):
        return PassBackend.create(PassBackendSettings(password_store_dir=store))

    @pytest.fixture
    def populated(self, store):
        for name in ("work/mail", "work/eu/tax", "workshop/lathe"):
            path = store / f"{name}.gpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"\x01ciphertext")
        return store

    def moves(self, recorded_runs):
        """The (source, destination) pair of every `pass mv` that was run."""
        return [
            tuple(cmd[cmd.index("--") + 1 :]) for cmd, _ in recorded_runs if "mv" in cmd
        ]

    def test_every_entry_under_it_is_moved(
        self, pass_on_path, populated, recorded_runs
    ):
        self.create(populated).move_folder("work", "archive/2019")

        assert sorted(self.moves(recorded_runs)) == [
            ("work/eu/tax", "archive/2019/eu/tax"),
            ("work/mail", "archive/2019/mail"),
        ]

    def test_a_sibling_whose_name_starts_the_same_is_not_taken_along(
        self, pass_on_path, populated, recorded_runs
    ):
        self.create(populated).move_folder("work", "archive")

        assert not [move for move in self.moves(recorded_runs) if "workshop" in move[0]]

    def test_a_folder_that_is_not_there_runs_nothing(
        self, pass_on_path, populated, recorded_runs
    ):
        backend = self.create(populated)

        with pytest.raises(FileNotFoundError):
            backend.move_folder("absent", "archive")

        assert self.moves(recorded_runs) == []

    def test_a_clash_runs_nothing_at_all(self, pass_on_path, populated, recorded_runs):
        """Not even the entries that would not have clashed.

        Half a folder moved is a folder in two places, and nothing says which
        half went.
        """
        clashing = populated / "archive" / "mail.gpg"
        clashing.parent.mkdir(parents=True)
        clashing.write_bytes(b"\x01ciphertext")
        backend = self.create(populated)

        with pytest.raises(FileExistsError):
            backend.move_folder("work", "archive")

        assert self.moves(recorded_runs) == []

    def test_the_names_are_still_terminated(
        self, pass_on_path, populated, recorded_runs
    ):
        """A folder move is another call site, and the rule is every one."""
        self.create(populated).move_folder("work", "archive")

        assert all("--" in cmd for cmd, _ in recorded_runs if "mv" in cmd)


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


class TestPassCannotRunForever:
    """Every pass invocation is bounded, as every git invocation already is.

    A decrypt raises a pinentry prompt, and gpg waits for it indefinitely -- so
    a prompt nobody answers, or one that never appears because there is no
    pinentry to run, leaves pass running and the worker that called it wedged.
    The manager's pool has four of those, and the window joins them at quit.
    """

    def backend(self, store, command):
        """A backend pointed at ``command`` instead of at pass.

        Constructed directly: create() insists on a real pass on PATH, and what
        is being tested is what happens once one is running.
        """
        return PassBackend(
            pass_cmd=command,
            env=dict(os.environ),
            password_store_dir=store,
            use_git=False,
        )

    @pytest.fixture
    def impatient(self, monkeypatch):
        """Shorten the deadline, so the test does not have to wait it out."""
        monkeypatch.setattr("gtkpass.backends.pass_cli.SUBPROCESS_TIMEOUT_SECONDS", 0.2)

    def test_a_pass_that_never_returns_is_given_up_on(self, store, impatient):
        backend = self.backend(store, ["sh", "-c", "sleep 30"])

        with pytest.raises(BackendError, match="timed out"):
            backend._run_pass(["show", "anything"])

    def test_it_gives_up_rather_than_waiting_for_the_process(self, store, impatient):
        backend = self.backend(store, ["sh", "-c", "sleep 30"])
        started = time.monotonic()

        with pytest.raises(BackendError):
            backend._run_pass(["show", "anything"])

        assert time.monotonic() - started < 10

    def test_what_it_printed_before_hanging_stays_out_of_the_error(
        self, store, impatient
    ):
        """TimeoutExpired carries the output captured so far.

        For `pass show` that output is the decrypted entry, and this error is
        shown to the user in a toast and written to the log.
        """
        backend = self.backend(store, ["sh", "-c", "echo SUPERSECRET; sleep 30"])

        with pytest.raises(BackendError) as raised:
            backend._run_pass(["show", "anything"])

        assert "SUPERSECRET" not in str(raised.value)


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

    def test_it_counts_what_is_still_to_push(self, pass_on_path, git_store):
        from conftest import git

        backend = PassBackend.create(PassBackendSettings(password_store_dir=git_store))
        (git_store / "email.gpg").write_bytes(b"\x01ciphertext")
        git("add", "-A", cwd=git_store)
        git("commit", "-m", "Add email", cwd=git_store)

        assert backend.unpushed_commits() == 1

    def test_a_store_that_is_not_offered_counts_nothing(self, pass_on_path, git_store):
        backend = PassBackend.create(
            PassBackendSettings(password_store_dir=git_store, use_git=False)
        )

        assert backend.unpushed_commits() == 0
