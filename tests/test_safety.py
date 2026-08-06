"""Guards that keep real secrets out of logs, transcripts and test runs.

Both of these exist because of near misses, not theory. A dataclass repr will
happily print a decrypted password into a log line, a traceback or a pytest
assertion diff; and a development probe pointed at the developer's own store
reads real passwords for no good reason.
"""

from pathlib import Path

import pytest

from gtkpass.backends import PasswordEntry
from gtkpass.safety import RealStoreBlocked, ensure_store_allowed, is_real_store

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
