"""Behaviour of the native GPG backend, against a real password store.

DirectBackend could not be instantiated at all before this suite existed: it
implemented a superseded interface, so five abstract methods were missing and
``create()`` raised TypeError, which the window swallowed into a generic
"backend not available" message.
"""

import shutil
import subprocess

import pytest

from gtkpass.backends import BackendError, PasswordEntry, PasswordMetadata
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
