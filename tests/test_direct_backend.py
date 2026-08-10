"""Behaviour of the native GPG backend, against a real password store.

DirectBackend could not be instantiated at all before this suite existed: it
implemented a superseded interface, so five abstract methods were missing and
``create()`` raised TypeError, which the window swallowed into a generic
"backend not available" message.
"""

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from gtkpass.backends import (
    BackendError,
    GPGError,
    PasswordEntry,
    PasswordMetadata,
    RecipientsChanged,
)
from gtkpass.backends.direct import DirectBackend, DirectBackendSettings

pytestmark = pytest.mark.requires_gpg

KEY_ID = "gtkpass-test@example.invalid"


@pytest.fixture(scope="session")
def gpg_home(tmp_path_factory):
    """A throwaway GPG home with a single usable key."""
    if shutil.which("gpg") is None:
        pytest.skip("gpg is not installed")

    home = tmp_path_factory.mktemp("gnupg")
    home.chmod(0o700)
    result = subprocess.run(
        [
            "gpg",
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--quick-generate-key",
            f"GTKPass Test <{KEY_ID}>",
            "default",
            "default",
            "never",
        ],
        env={"GNUPGHOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"could not generate a test key: {result.stderr}")
    return home


@pytest.fixture
def store(tmp_path):
    """An empty password store whose root is encrypted to the test key."""
    root = tmp_path / "store"
    root.mkdir()
    (root / ".gpg-id").write_text(f"{KEY_ID}\n")
    return root


@pytest.fixture
def backend(store, gpg_home):
    return DirectBackend.create(
        DirectBackendSettings(password_store_dir=store, gpg_home=gpg_home)
    )


class TestCreate:
    def test_uses_the_configured_store_directory(self, backend, store):
        """Availability must not be judged against ~/.password-store.

        is_available() checked the default location and ignored the settings,
        so a configured store reported itself unavailable.
        """
        assert backend.password_store_dir == store

    def test_rejects_a_missing_directory(self, tmp_path, gpg_home):
        with pytest.raises(BackendError):
            DirectBackend.create(
                DirectBackendSettings(
                    password_store_dir=tmp_path / "nope", gpg_home=gpg_home
                )
            )


class TestRoundTrip:
    def test_add_then_list(self, backend):
        backend.add_password("email/work", "hunter2\nusername: alice\n")

        names = [entry.name for entry in backend.list_passwords()]

        assert names == ["email/work"]

    def test_list_returns_metadata_not_entries(self, backend):
        backend.add_password("solo", "s3cret\n")

        (entry,) = backend.list_passwords()

        assert isinstance(entry, PasswordMetadata)
        assert entry.modified > 0

    def test_add_then_read_back(self, backend):
        backend.add_password("email/work", "hunter2\nusername: alice\n")

        entry = backend.get_password("email/work")

        assert isinstance(entry, PasswordEntry)
        assert entry.password == "hunter2"
        assert entry.metadata["username"] == "alice"

    def test_list_can_be_filtered_by_prefix(self, backend):
        backend.add_password("email/work", "a\n")
        backend.add_password("bank/giro", "b\n")

        names = [entry.name for entry in backend.list_passwords(prefix="email/")]

        assert names == ["email/work"]

    def test_git_directory_is_not_listed(self, backend, store):
        backend.add_password("real", "a\n")
        git_dir = store / ".git"
        git_dir.mkdir()
        (git_dir / "spurious.gpg").write_bytes(b"not a password")

        names = [entry.name for entry in backend.list_passwords()]

        assert names == ["real"]


class TestMissingEntries:
    def test_get_password_raises_for_unknown_name(self, backend):
        """The interface promises FileNotFoundError; returning None made the
        detail view fail later, far from the cause."""
        with pytest.raises(FileNotFoundError):
            backend.get_password("does/not/exist")

    def test_add_refuses_to_overwrite(self, backend):
        backend.add_password("dup", "a\n")

        with pytest.raises(FileExistsError):
            backend.add_password("dup", "b\n")

    def test_edit_requires_an_existing_entry(self, backend):
        with pytest.raises(FileNotFoundError):
            backend.edit_password("ghost", "a\n")

    def test_delete_requires_an_existing_entry(self, backend):
        with pytest.raises(FileNotFoundError):
            backend.delete_password("ghost")


class TestMutation:
    def test_edit_replaces_content(self, backend):
        backend.add_password("entry", "old\n")

        backend.edit_password("entry", "new\nusername: bob\n")

        entry = backend.get_password("entry")
        assert entry.password == "new"
        assert entry.metadata["username"] == "bob"

    def test_delete_removes_the_entry(self, backend):
        backend.add_password("doomed", "a\n")

        backend.delete_password("doomed")

        assert backend.list_passwords() == []

    def test_delete_prunes_empty_directories(self, backend, store):
        backend.add_password("nested/deep/entry", "a\n")

        backend.delete_password("nested/deep/entry")

        assert not (store / "nested").exists()

    def test_move_renames(self, backend):
        backend.add_password("before", "a\n")

        backend.move_password("before", "after")

        assert [e.name for e in backend.list_passwords()] == ["after"]
        assert backend.get_password("after").password == "a"

    def test_move_refuses_to_clobber(self, backend):
        backend.add_password("one", "a\n")
        backend.add_password("two", "b\n")

        with pytest.raises(FileExistsError):
            backend.move_password("one", "two")

    def test_copy_duplicates(self, backend):
        backend.add_password("original", "a\n")

        backend.copy_password("original", "duplicate")

        assert sorted(e.name for e in backend.list_passwords()) == [
            "duplicate",
            "original",
        ]


class TestSearch:
    def test_matches_substrings_case_insensitively(self, backend):
        backend.add_password("email/Work", "a\n")
        backend.add_password("bank/giro", "b\n")

        assert [e.name for e in backend.search("WORK")] == ["email/Work"]

    def test_no_match_is_empty(self, backend):
        backend.add_password("email/work", "a\n")

        assert backend.search("zzz") == []


class TestRecipientResolution:
    def test_a_subdirectory_gpg_id_takes_precedence(self, backend, store):
        """pass looks for the nearest .gpg-id walking up from the entry.

        Reading only the store root silently encrypts to the wrong key in any
        store that delegates a subtree to a different set of recipients.
        """
        team = store / "team"
        team.mkdir()
        (team / ".gpg-id").write_text(f"{KEY_ID}\n")

        backend.add_password("team/shared", "s3cret\n")

        assert backend.get_password("team/shared").password == "s3cret"

    def test_missing_gpg_id_is_reported(self, tmp_path, gpg_home):
        root = tmp_path / "unsigned"
        root.mkdir()
        backend = DirectBackend.create(
            DirectBackendSettings(password_store_dir=root, gpg_home=gpg_home)
        )

        with pytest.raises(BackendError, match="gpg-id"):
            backend.add_password("entry", "a\n")


@pytest.mark.requires_git
class TestCommittingToAGitStore:
    """The `commit` flag was accepted and dropped by every backend.

    DirectBackend writes .gpg files straight to disk, so unless it commits them
    itself a git-backed store drifts out of step with its own history -- which
    is what produces an unexplained non-fast-forward at the next push.
    """

    @pytest.fixture
    def git_store(self, tmp_path, gpg_home):
        from conftest import git, init_repo

        root = init_repo(tmp_path / "store")
        (root / ".gpg-id").write_text(f"{KEY_ID}\n")
        git("add", "-A", cwd=root)
        git("commit", "-m", "Set the recipient", cwd=root)
        return root

    @pytest.fixture
    def backend(self, git_store, gpg_home):
        return DirectBackend.create(
            DirectBackendSettings(password_store_dir=git_store, gpg_home=gpg_home)
        )

    def revisions(self, store):
        from conftest import git

        return int(git("rev-list", "--count", "HEAD", cwd=store))

    def test_a_new_entry_is_committed(self, backend, git_store):
        from conftest import git

        before = self.revisions(git_store)

        backend.add_password("email/work", "hunter2\n")

        assert self.revisions(git_store) == before + 1
        assert git("status", "--porcelain", cwd=git_store) == ""

    def test_the_commit_message_names_the_entry(self, backend, git_store):
        from conftest import git

        backend.add_password("email/work", "hunter2\n")

        assert "email/work" in git("log", "-1", "--pretty=%s", cwd=git_store)

    def test_the_commit_message_does_not_carry_the_password(self, backend, git_store):
        from conftest import git

        backend.add_password("email/work", "hunter2\n")

        assert "hunter2" not in git("log", "-1", "--pretty=%B", cwd=git_store)

    def test_an_edit_is_committed(self, backend, git_store):
        backend.add_password("email/work", "hunter2\n")
        before = self.revisions(git_store)

        backend.edit_password("email/work", "hunter3\n")

        assert self.revisions(git_store) == before + 1

    def test_a_deletion_is_committed_as_a_removal(self, backend, git_store):
        from conftest import git

        backend.add_password("email/work", "hunter2\n")

        backend.delete_password("email/work")

        assert git("status", "--porcelain", cwd=git_store) == ""
        assert "email/work.gpg" not in git("ls-files", cwd=git_store)

    def test_not_committing_can_be_asked_for(self, backend, git_store):
        from conftest import git

        before = self.revisions(git_store)

        backend.add_password("email/work", "hunter2\n", commit=False)

        assert self.revisions(git_store) == before
        # -uall: without it an untracked directory collapses to "?? email/".
        assert "email/work.gpg" in git("status", "--porcelain", "-uall", cwd=git_store)

    def test_the_entry_is_still_written_when_not_committing(self, backend, git_store):
        backend.add_password("email/work", "hunter2\n", commit=False)

        assert backend.get_password("email/work").password == "hunter2"


@pytest.mark.requires_git
class TestAStoreWithoutGitStillWorks:
    """git is optional: plenty of stores are a plain directory."""

    def test_writing_to_a_plain_directory_is_unaffected(self, backend):
        backend.add_password("email/work", "hunter2\n")

        assert backend.get_password("email/work").password == "hunter2"

    def test_it_reports_that_it_cannot_sync(self, backend):
        from gtkpass.backends import SyncUnavailable

        capability = backend.sync_capability()

        assert not capability.supported
        assert capability.reason is SyncUnavailable.NOT_A_REPO


class TestWritingWaitsForTheRecipientsToBeApproved:
    """A store whose .gpg-id changed is not written to until somebody looks.

    Encrypting now would encrypt to whoever that file names today, and whether
    that is who it should name is the entire question. Reading is left alone:
    nothing newly named can decrypt what is already there.
    """

    def with_approved(self, store, gpg_home, approved):
        return DirectBackend.create(
            DirectBackendSettings(
                password_store_dir=store,
                gpg_home=gpg_home,
                approved_recipients=approved,
            )
        )

    #: A record naming somebody who is not in this store's .gpg-id.
    STALE = ". someone-else@example.invalid"

    def test_a_store_seen_for_the_first_time_is_written_to(self, backend):
        """Nothing to have changed from, so nothing is refused."""
        backend.add_password("email/work", "hunter2\n")

        assert backend.get_password("email/work").password == "hunter2"

    def test_a_changed_recipient_set_refuses_a_write(self, store, gpg_home):
        blocked = self.with_approved(store, gpg_home, self.STALE)

        with pytest.raises(RecipientsChanged):
            blocked.add_password("email/work", "hunter2\n")

    def test_an_edit_is_refused_too(self, backend, store, gpg_home):
        backend.add_password("email/work", "hunter2\n")
        blocked = self.with_approved(store, gpg_home, self.STALE)

        with pytest.raises(RecipientsChanged):
            blocked.edit_password("email/work", "hunter3\n")

    def test_reading_is_not_refused(self, backend, store, gpg_home):
        backend.add_password("email/work", "hunter2\n")
        blocked = self.with_approved(store, gpg_home, self.STALE)

        assert blocked.get_password("email/work").password == "hunter2"
        assert [entry.name for entry in blocked.list_passwords()] == ["email/work"]

    def test_the_refusal_carries_what_changed(self, store, gpg_home):
        blocked = self.with_approved(store, gpg_home, self.STALE)

        with pytest.raises(RecipientsChanged) as raised:
            blocked.add_password("email/work", "hunter2\n")

        assert raised.value.audit.changed
        assert KEY_ID in raised.value.audit.added

    def test_approving_what_the_store_says_lifts_it(self, store, gpg_home):
        from gtkpass.backends import recipients

        approved = recipients.record(recipients.configuration(store))
        allowed = self.with_approved(store, gpg_home, approved)

        allowed.add_password("email/work", "hunter2\n")

        assert allowed.get_password("email/work").password == "hunter2"


class TruncatingGPG:
    """A gpg that opens its output file, writes, and then fails.

    Not a caricature. gpg opens ``--output`` for writing before it knows whether
    it can encrypt at all, so a failure part-way -- an unusable recipient, a full
    disk, a kill signal -- leaves the file created and short. Writing straight to
    the entry therefore destroys it in exchange for nothing.

    A fake that merely returned ``ok=False`` without touching the file would pass
    against the code this exists to catch, which is why this one writes.
    """

    def __init__(self):
        self.outputs: list[str] = []

    def encrypt(self, content, recipients, armor=False, output=None, **kwargs):
        self.outputs.append(output)
        Path(output).write_bytes(b"truncated")
        return SimpleNamespace(ok=False, status="unusable public key")


class TestAFailedWriteLeavesTheEntryAlone:
    """Editing is the only destructive thing the interface can do to a store.

    There is no undo and no second copy, so an encrypt that fails half way must
    cost the edit rather than the entry.
    """

    @pytest.fixture
    def entry(self, backend, store):
        """One real, readable entry, written by real gpg."""
        backend.add_password("email/work", "hunter2\nusername: someone\n")
        return store / "email" / "work.gpg"

    def test_the_previous_entry_survives(self, backend, entry):
        before = entry.read_bytes()
        backend.gpg = TruncatingGPG()

        with pytest.raises(GPGError):
            backend.edit_password("email/work", "replacement\n")

        assert entry.read_bytes() == before

    def test_it_stays_decryptable(self, backend, entry, gpg_home, store):
        """Bytes being equal is the mechanism; this is what it is for."""
        backend.gpg = TruncatingGPG()
        with pytest.raises(GPGError):
            backend.edit_password("email/work", "replacement\n")

        fresh = DirectBackend.create(
            DirectBackendSettings(password_store_dir=store, gpg_home=gpg_home)
        )

        assert fresh.get_password("email/work").password == "hunter2"

    def test_gpg_is_never_pointed_at_the_entry_itself(self, backend, entry):
        gpg = TruncatingGPG()
        backend.gpg = gpg

        with pytest.raises(GPGError):
            backend.edit_password("email/work", "replacement\n")

        assert gpg.outputs, "nothing was encrypted, so this proves nothing"
        assert str(entry) not in gpg.outputs

    def test_a_failed_write_leaves_no_debris(self, backend, entry):
        backend.gpg = TruncatingGPG()

        with pytest.raises(GPGError):
            backend.edit_password("email/work", "replacement\n")

        assert list(entry.parent.iterdir()) == [entry]

    def test_a_failed_add_creates_nothing(self, backend, store):
        backend.gpg = TruncatingGPG()

        with pytest.raises(GPGError):
            backend.add_password("email/new", "secret\n")

        assert not (store / "email" / "new.gpg").exists()
        assert list((store / "email").iterdir()) == []


class TestWritingPreservesHowTheEntryWasStored:
    def test_an_edit_keeps_the_entry_permissions(self, backend, store):
        """os.replace carries the temporary file's mode, not the entry's.

        A store kept at 0600 would otherwise be relaxed to whatever the umask
        gave the new file, one entry at a time, as they were edited.
        """
        backend.add_password("email/work", "hunter2\n")
        entry = store / "email" / "work.gpg"
        entry.chmod(0o600)

        backend.edit_password("email/work", "hunter3\n")

        assert entry.stat().st_mode & 0o777 == 0o600

    def test_a_successful_write_leaves_no_temporary_behind(self, backend, store):
        backend.add_password("email/work", "hunter2\n")

        assert [p.name for p in (store / "email").iterdir()] == ["work.gpg"]
