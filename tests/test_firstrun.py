"""Recognising a password store that is already there.

The first-run screen handed the user a preferences dialog with four backend
type names in a combo box. The common case -- somebody who already uses `pass`
-- can be recognised instead.
"""

import pytest

from gtkpass import firstrun


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A directory shaped like a password store, in place of the real one.

    Marked as a scratch store rather than opted in to. Pointing
    PASSWORD_STORE_DIR at it makes the guard treat it as the user's own, and
    the marker is the project's own way of saying otherwise -- reaching for
    GTKPASS_ALLOW_REAL_STORE here would disarm the guard for the whole test.
    """
    from gtkpass.safety import SCRATCH_MARKER

    store = tmp_path / ".password-store"
    store.mkdir()
    (store / firstrun.STORE_MARKER).write_text("ABCDEF01\n")
    (store / SCRATCH_MARKER).touch()
    monkeypatch.setenv("PASSWORD_STORE_DIR", str(store))
    return store


class TestFindingAStore:
    def test_a_store_is_found(self, store):
        assert firstrun.existing_store() == store

    def test_nothing_is_found_when_there_is_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASSWORD_STORE_DIR", str(tmp_path / "absent"))

        assert firstrun.existing_store() is None

    def test_a_directory_without_recipients_is_not_a_store(self, store):
        """Any directory can be called that. One with a .gpg-id is one."""
        (store / firstrun.STORE_MARKER).unlink()

        assert firstrun.existing_store() is None

    def test_a_file_where_the_store_should_be_is_not_a_store(
        self, tmp_path, monkeypatch
    ):
        impostor = tmp_path / "store"
        impostor.write_text("not a directory")
        monkeypatch.setenv("PASSWORD_STORE_DIR", str(impostor))

        assert firstrun.existing_store() is None

    def test_a_store_the_guard_refuses_is_not_offered(self, store, monkeypatch):
        """A checkout may not open the real store, so it may not offer it.

        A button that cannot work is worse than no button: it turns the guard's
        refusal into something the user did.
        """
        monkeypatch.setattr(firstrun, "ensure_store_allowed", _refuse)

        assert firstrun.existing_store() is None


def _refuse(path):
    from gtkpass.safety import RealStoreBlocked

    raise RealStoreBlocked(f"nope: {path}")


class TestChoosingABackend:
    def test_pass_is_preferred_when_it_is_installed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(firstrun.shutil, "which", lambda name: "/usr/bin/pass")

        assert firstrun.backend_type_for(tmp_path) == "pass"

    def test_the_native_backend_is_used_without_it(self, monkeypatch, tmp_path):
        monkeypatch.setattr(firstrun.shutil, "which", lambda name: None)

        assert firstrun.backend_type_for(tmp_path) == "direct"
