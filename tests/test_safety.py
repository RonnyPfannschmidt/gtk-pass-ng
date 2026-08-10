"""Guards that keep real secrets out of logs, transcripts and test runs.

Both of these exist because of near misses, not theory. A dataclass repr will
happily print a decrypted password into a log line, a traceback or a pytest
assertion diff; and a development probe pointed at the developer's own store
reads real passwords for no good reason.
"""

import json
from pathlib import Path

import pytest

from gtkpass import safety
from gtkpass.backends import PasswordEntry
from gtkpass.safety import (
    SCRATCH_MARKER,
    NotInstalled,
    RealStoreBlocked,
    ensure_keyring_allowed,
    ensure_store_allowed,
    is_real_store,
    opted_in,
    require_installed,
    running_from_checkout,
)


def scratch_store(path: Path) -> Path:
    """A store marked the way ``make devstore`` marks one."""
    path.mkdir(parents=True, exist_ok=True)
    (path / SCRATCH_MARKER).write_text("")
    return path


def fake_distribution(
    base: Path, editable: bool | None = None, direct_url=None, metadata_dir=None
):
    """Stands in for what importlib.metadata hands back.

    ``base`` is where the distribution says its files live, which is the
    site-packages directory for a real one. ``editable`` writes the direct_url
    metadata pip and uv record; leaving it unset means no direct_url.json at
    all, which is what an RPM or a wheel from an index looks like.
    ``metadata_dir`` is the directory the metadata itself lives in, which is how
    an installed .dist-info is told from a source tree's .egg-info.
    """
    if direct_url is None and editable is not None:
        direct_url = json.dumps(
            {"url": base.as_uri(), "dir_info": {"editable": editable}}
        )
    path = metadata_dir if metadata_dir is not None else base / "gtkpass-0.1.dist-info"

    class Fake:
        _path = path

        def read_text(self, filename):
            return direct_url if filename == "direct_url.json" else None

        def locate_file(self, relative):
            return base / relative

    return Fake()


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


class TestWhereTheCodeIsRunningFrom:
    """What decides the guard's default, now that nothing sets it for us.

    An installed build is the application being used, and refusing its owner's
    store would make it useless. A checkout is where the probes, experiments and
    one-off scripts live, and that is what has to stay shut by default. So the
    default follows which of the two is running, and anything it cannot tell
    apart counts as a checkout.
    """

    def test_an_editable_install_is_a_checkout(self, tmp_path, monkeypatch):
        """What `make sync` produces, and what the flag exists to say."""
        dist = fake_distribution(tmp_path / "site-packages", editable=True)
        monkeypatch.setattr("gtkpass.safety._own_distribution", lambda: dist)
        assert running_from_checkout(tmp_path / "src" / "gtkpass" / "safety.py")

    def test_an_ordinary_install_is_not(self, tmp_path, monkeypatch):
        """An RPM, or a wheel from an index: no direct_url.json at all."""
        site = tmp_path / "site-packages"
        dist = fake_distribution(site)
        monkeypatch.setattr("gtkpass.safety._own_distribution", lambda: dist)
        assert not running_from_checkout(site / "gtkpass" / "safety.py")

    def test_installing_a_local_directory_is_not(self, tmp_path, monkeypatch):
        """`pip install .` records where it came from, but is not editable."""
        site = tmp_path / "site-packages"
        dist = fake_distribution(site, editable=False)
        monkeypatch.setattr("gtkpass.safety._own_distribution", lambda: dist)
        assert not running_from_checkout(site / "gtkpass" / "safety.py")

    def test_no_metadata_at_all_is_a_checkout(self, tmp_path, monkeypatch):
        """`PYTHONPATH=src python -m gtkpass` installs nothing to describe it.

        Nothing can be established about such a run, and the case that cannot be
        established is the one that has to stay shut.
        """
        monkeypatch.setattr("gtkpass.safety._own_distribution", lambda: None)
        assert running_from_checkout(tmp_path / "src" / "gtkpass" / "safety.py")

    def test_unreadable_metadata_is_a_checkout(self, tmp_path, monkeypatch):
        """A direct_url.json that will not parse decides nothing either."""
        site = tmp_path / "site-packages"
        dist = fake_distribution(site, direct_url="{ this is not json")
        monkeypatch.setattr("gtkpass.safety._own_distribution", lambda: dist)
        assert running_from_checkout(site / "gtkpass" / "safety.py")

    def test_a_checkout_shadowing_an_installed_copy_is_a_checkout(
        self, tmp_path, monkeypatch
    ):
        """The case the metadata alone gets wrong, and the dangerous direction.

        With a release installed system-wide and a checkout ahead of it on the
        path, ``importlib.metadata`` finds the installed distribution and calls
        the run an installed build -- while the code actually executing is the
        working copy. So the metadata is believed only when it describes the
        module that is running.
        """
        dist = fake_distribution(tmp_path / "site-packages")
        monkeypatch.setattr("gtkpass.safety._own_distribution", lambda: dist)
        assert running_from_checkout(tmp_path / "src" / "gtkpass" / "safety.py")

    def test_a_stale_egg_info_does_not_count_as_installed(self, tmp_path, monkeypatch):
        """The hole a bare metadata lookup leaves open.

        A `setup.py` or `pip install` run at any point in the past leaves a
        `src/gtkpass.egg-info` behind, and it stays there. It satisfies
        importlib.metadata, carries no direct_url.json, and sits beside the
        package -- so a PYTHONPATH run out of the checkout looked like an
        ordinary install and opened the guard. An .egg-info is a build artefact
        inside a source tree, which is the opposite of an installation.
        """
        src = tmp_path / "src"
        dist = fake_distribution(src, metadata_dir=src / "gtkpass.egg-info")
        monkeypatch.setattr("gtkpass.safety._own_distribution", lambda: dist)

        assert running_from_checkout(src / "gtkpass" / "safety.py")

    def test_this_very_test_run_is_a_checkout(self):
        """The tripwire. If this ever fails, the suite is running unguarded."""
        assert running_from_checkout()


class TestTheDefaultFollowsWhereTheCodeIsFrom:
    """The environment variable still decides when it is set, both ways."""

    def test_a_checkout_defaults_to_refusing(self, monkeypatch):
        monkeypatch.delenv("GTKPASS_ALLOW_REAL_STORE", raising=False)
        monkeypatch.setattr("gtkpass.safety.running_from_checkout", lambda *a: True)
        assert not opted_in()

    def test_an_installed_build_defaults_to_allowing(self, monkeypatch):
        monkeypatch.delenv("GTKPASS_ALLOW_REAL_STORE", raising=False)
        monkeypatch.setattr("gtkpass.safety.running_from_checkout", lambda *a: False)
        assert opted_in()

    def test_an_installed_build_can_still_be_turned_off(self, monkeypatch):
        """Someone auditing an installed build gets to shut it, same as anyone."""
        monkeypatch.setenv("GTKPASS_ALLOW_REAL_STORE", "0")
        monkeypatch.setattr("gtkpass.safety.running_from_checkout", lambda *a: False)
        assert not opted_in()

    def test_a_checkout_can_still_opt_in(self, monkeypatch):
        """run_app.sh does exactly this."""
        monkeypatch.setenv("GTKPASS_ALLOW_REAL_STORE", "1")
        monkeypatch.setattr("gtkpass.safety.running_from_checkout", lambda *a: True)
        assert opted_in()

    def test_an_empty_value_does_not_count_as_a_decision(self, monkeypatch):
        """`FOO= gtkpass` sets it to nothing; that is not an opt-out."""
        monkeypatch.setenv("GTKPASS_ALLOW_REAL_STORE", "")
        monkeypatch.setattr("gtkpass.safety.running_from_checkout", lambda *a: False)
        assert opted_in()


class TestTheGuardIsActiveDuringTests:
    """conftest clears the opt-in; this is the tripwire that says so."""

    def test_the_opt_in_is_not_set(self):
        import os

        assert "GTKPASS_ALLOW_REAL_STORE" not in os.environ

    def test_an_exported_opt_in_would_be_cleared(self):
        """Even if the surrounding shell exports it, the run must not inherit it."""
        from gtkpass.safety import opted_in

        assert not opted_in()


class TestWhichDistributionAnswers:
    """A source tree can offer two, and the answer must not depend on luck.

    Building an sdist leaves a `src/*.egg-info` behind, and an editable install
    puts `src/` on the path -- so both that and the real `.dist-info` describe
    the same distribution. Whichever `importlib.metadata` happened to return
    first then decided whether the application would start at all.
    """

    @pytest.fixture(autouse=True)
    def _forget_the_cached_answer(self):
        """It is resolved once per process; these tests change what it sees."""
        safety._own_distribution.cache_clear()
        yield
        safety._own_distribution.cache_clear()

    def test_a_real_install_wins_over_a_source_tree_artefact(
        self, tmp_path, monkeypatch
    ):
        egg = fake_distribution(
            tmp_path / "src", metadata_dir=tmp_path / "src" / "gtk_pass.egg-info"
        )
        installed = fake_distribution(tmp_path / "site-packages")

        for order in ([egg, installed], [installed, egg]):
            monkeypatch.setattr(
                "gtkpass.safety._distributions_named", lambda _o=order: list(_o)
            )
            safety._own_distribution.cache_clear()
            assert safety._own_distribution() is installed

    def test_a_source_tree_artefact_is_returned_when_it_is_all_there_is(
        self, tmp_path, monkeypatch
    ):
        """So require_installed() can refuse it by name rather than silently."""
        egg = fake_distribution(
            tmp_path / "src", metadata_dir=tmp_path / "src" / "gtk_pass.egg-info"
        )
        monkeypatch.setattr("gtkpass.safety._distributions_named", lambda: [egg])
        safety._own_distribution.cache_clear()

        assert safety._own_distribution() is egg


class TestAnInstallIsRequired:
    """Running from a bare source tree is refused outright.

    `PYTHONPATH=src python -m gtkpass` produces a process with no distribution
    metadata, which means nothing can be established about what is running --
    not its version, and not whether it is somebody's working copy. Rather than
    guess, the import fails and says what to do. It also removes the one case
    the guard could not answer honestly.
    """

    def test_an_installed_copy_is_accepted(self):
        """This suite runs against the editable install `make sync` creates."""
        require_installed()

    def test_a_bare_source_tree_is_refused(self, monkeypatch):
        monkeypatch.setattr("gtkpass.safety._own_distribution", lambda: None)

        with pytest.raises(NotInstalled, match="make sync"):
            require_installed()

    def test_a_stale_egg_info_is_not_an_install(self, tmp_path, monkeypatch):
        """It is what a source tree accumulates, not what installing produces."""
        src = tmp_path / "src"
        dist = fake_distribution(src, metadata_dir=src / "gtkpass.egg-info")
        monkeypatch.setattr("gtkpass.safety._own_distribution", lambda: dist)

        with pytest.raises(NotInstalled, match=r"egg-info"):
            require_installed()
