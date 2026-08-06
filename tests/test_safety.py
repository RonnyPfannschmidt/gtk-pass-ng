"""Guards that keep real secrets out of logs, transcripts and test runs.

Both of these exist because of near misses, not theory. A dataclass repr will
happily print a decrypted password into a log line, a traceback or a pytest
assertion diff; and a development probe pointed at the developer's own store
reads real passwords for no good reason.
"""

from pathlib import Path

import pytest

from gtkpass.backends import PasswordEntry
from gtkpass.safety import (
    SCRATCH_MARKER,
    RealStoreBlocked,
    ensure_keyring_allowed,
    ensure_store_allowed,
    is_real_store,
    opted_in,
)


def scratch_store(path: Path) -> Path:
    """A store marked the way ``make devstore`` marks one."""
    path.mkdir(parents=True, exist_ok=True)
    (path / SCRATCH_MARKER).write_text("")
    return path


SECRET = "correct-horse-battery-staple"


def entry(content: str | None = SECRET) -> PasswordEntry:
    return PasswordEntry(
        name="email/work", path=Path("/store/email/work.gpg"), content=content
    )


class TestSecretsStayOutOfText:
    """Anything that renders an entry as text must not render the secret."""

    def test_repr_hides_the_content(self):
        assert SECRET not in repr(entry())

    def test_str_hides_the_content(self):
        assert SECRET not in str(entry())

    def test_interpolation_hides_the_content(self):
        """This is the shape a log line takes."""
        assert SECRET not in f"loaded {entry()}"

    def test_repr_still_identifies_the_entry(self):
        """Redaction must not make debugging impossible."""
        text = repr(entry())

        assert "email/work" in text
        assert "loaded" in text

    def test_repr_says_when_nothing_is_loaded(self):
        assert "empty" in repr(entry(content=None))

    def test_the_password_is_still_reachable_deliberately(self):
        """Redaction is about accidental disclosure, not access."""
        assert entry().password == SECRET


class TestRealStoreGuard:
    """Development and test code must not read the developer's own store."""

    @pytest.fixture(autouse=True)
    def _no_override(self, monkeypatch):
        monkeypatch.delenv("GTKPASS_ALLOW_REAL_STORE", raising=False)
        monkeypatch.delenv("PASSWORD_STORE_DIR", raising=False)

    def test_the_default_store_is_recognised(self):
        assert is_real_store(Path("~/.password-store").expanduser())

    def test_the_configured_store_is_recognised(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PASSWORD_STORE_DIR", str(tmp_path))

        assert is_real_store(tmp_path)

    def test_a_scratch_store_is_not(self, tmp_path):
        assert not is_real_store(tmp_path / "scratch")

    def test_scratch_stores_are_allowed(self, tmp_path):
        ensure_store_allowed(tmp_path / "scratch")

    def test_the_real_store_is_refused(self):
        with pytest.raises(RealStoreBlocked, match="GTKPASS_ALLOW_REAL_STORE"):
            ensure_store_allowed(Path("~/.password-store").expanduser())

    def test_the_application_can_opt_in(self, monkeypatch):
        """run_app.sh sets this; ad-hoc probes and pytest do not."""
        monkeypatch.setenv("GTKPASS_ALLOW_REAL_STORE", "1")

        ensure_store_allowed(Path("~/.password-store").expanduser())

    def test_the_opt_in_can_be_turned_back_off(self, monkeypatch):
        """`make run-dev` passes 0 so run_app.sh's default does not apply.

        Without this the development launcher inherits the opt-in from the
        script it launches through, and runs with the guard disabled.
        """
        monkeypatch.setenv("GTKPASS_ALLOW_REAL_STORE", "0")

        assert not opted_in()


class TestTheDevelopmentStore:
    """`make devstore` marks its store, so it needs no opt-in to be opened.

    Pointing PASSWORD_STORE_DIR at the scratch store used to classify it as the
    real one, which is why the development launcher had to disable the guard
    wholesale -- and then nothing was guarded at all.
    """

    @pytest.fixture(autouse=True)
    def _no_override(self, monkeypatch):
        monkeypatch.delenv("GTKPASS_ALLOW_REAL_STORE", raising=False)
        monkeypatch.delenv("PASSWORD_STORE_DIR", raising=False)

    def test_a_marked_store_is_not_real(self, tmp_path):
        assert not is_real_store(scratch_store(tmp_path / "dev"))

    def test_a_marked_store_stays_scratch_when_configured(self, monkeypatch, tmp_path):
        """This is exactly what `make run-dev` does."""
        store = scratch_store(tmp_path / "dev")
        monkeypatch.setenv("PASSWORD_STORE_DIR", str(store))

        assert not is_real_store(store)

    def test_a_marked_store_is_allowed_without_opting_in(self, tmp_path):
        ensure_store_allowed(scratch_store(tmp_path / "dev"))

    def test_the_real_store_is_still_refused_alongside_it(self, monkeypatch, tmp_path):
        """The guard stays armed for everything else during a dev run."""
        monkeypatch.setenv("PASSWORD_STORE_DIR", str(scratch_store(tmp_path / "dev")))

        with pytest.raises(RealStoreBlocked):
            ensure_store_allowed(Path("~/.password-store").expanduser())

    def test_the_default_store_cannot_be_marked_scratch(self, monkeypatch, tmp_path):
        """Or a stray marker in ~/.password-store would disarm the guard.

        The home directory is redirected here rather than a marker being
        written into the developer's actual store.
        """
        monkeypatch.setenv("HOME", str(tmp_path))
        home_store = scratch_store(tmp_path / ".password-store")

        assert is_real_store(home_store)


class TestTheKeyringIsGuardedToo:
    """The rule names the keyring, and only the file stores enforced it.

    SecretServiceBackend.is_available() opens the user's default collection,
    and the backend conformance suite calls it. Under `make test` that lands on
    a private bus with no service, but a bare pytest run reaches the real one.
    """

    @pytest.fixture(autouse=True)
    def _no_override(self, monkeypatch):
        monkeypatch.delenv("GTKPASS_ALLOW_REAL_STORE", raising=False)

    def test_the_keyring_is_refused(self):
        with pytest.raises(RealStoreBlocked, match="GTKPASS_ALLOW_REAL_STORE"):
            ensure_keyring_allowed()

    def test_the_application_can_opt_in(self, monkeypatch):
        monkeypatch.setenv("GTKPASS_ALLOW_REAL_STORE", "1")

        ensure_keyring_allowed()

    def test_the_backend_reports_unavailable_rather_than_raising(self):
        """is_available() gates the UI and must answer, not explode."""
        from gtkpass.backends.secretservice import SecretServiceBackend

        assert SecretServiceBackend.is_available() is False

    def test_the_backend_refuses_to_be_created(self):
        from gtkpass.backends.secretservice import SecretServiceBackend

        with pytest.raises(RealStoreBlocked):
            SecretServiceBackend.create()


class TestBackendsHonourTheGuard:
    def test_direct_backend_refuses_the_real_store(self, monkeypatch):
        from gtkpass.backends.direct import DirectBackend, DirectBackendSettings

        monkeypatch.delenv("GTKPASS_ALLOW_REAL_STORE", raising=False)
        real = Path("~/.password-store").expanduser()
        if not real.is_dir():
            pytest.skip("no real store on this machine")

        with pytest.raises(RealStoreBlocked):
            DirectBackend.create(DirectBackendSettings(password_store_dir=real))


class TestTheGuardIsActiveDuringTests:
    """conftest clears the opt-in; this is the tripwire that says so."""

    def test_the_opt_in_is_not_set(self):
        import os

        assert "GTKPASS_ALLOW_REAL_STORE" not in os.environ

    def test_an_exported_opt_in_would_be_cleared(self):
        """Even if the surrounding shell exports it, the run must not inherit it."""
        from gtkpass.safety import opted_in

        assert not opted_in()
