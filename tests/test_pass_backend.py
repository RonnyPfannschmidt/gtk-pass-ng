"""How the Pass backend invokes pass, inside a sandbox and outside one.

The packaged application bundles pass itself, so there is one answer in both
places: run it from PATH. The alternative -- asking the host to run it through
`flatpak-spawn --host` -- needs a permission that hands the application
arbitrary command execution outside the sandbox, which is not a trade a
password manager should make.
"""

import pytest

from gtkpass.backends import BackendError
from gtkpass.backends.pass_cli import PassBackend, PassBackendSettings


@pytest.fixture
def store(tmp_path):
    """A scratch store, so the guard has nothing to object to."""
    path = tmp_path / "store"
    path.mkdir()
    return path


@pytest.fixture
def pass_on_path(monkeypatch):
    monkeypatch.setattr(
        "gtkpass.backends.pass_cli.shutil.which",
        lambda command: "/usr/bin/pass" if command == "pass" else None,
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
