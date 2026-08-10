"""Test configuration and shared fixtures.

The GSettings schema must be compiled and pointed at *before* GLib resolves its
default schema source, which it caches on first use.  That is why the setup
happens in ``pytest_configure`` rather than in a fixture: fixtures run after
collection, and collection imports test modules.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SOURCE_DIR = REPO_ROOT / "data"

#: Populated by :func:`pytest_configure` so tests can introspect the schema XML.
COMPILED_SCHEMA_DIR: Path | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Compile the GSettings schema into a temp dir and point GLib at it.

    Also forces the in-memory GSettings backend so tests never read or write
    the developer's real dconf database.
    """
    global COMPILED_SCHEMA_DIR

    os.environ.setdefault("GSETTINGS_BACKEND", "memory")
    # Keep the accessibility bridge out of the way; it is noisy under xvfb.
    os.environ.setdefault("NO_AT_BRIDGE", "1")

    # GTK4 renders with OpenGL by default, and the tests that present a widget
    # realize one. On a machine with no GPU -- a CI container, which is the only
    # place this bites -- libepoxy aborts inside gdk_gl_context_make_current and
    # takes the whole process down: SIGABRT, no traceback, no test report, and
    # every test after it simply never runs.
    #
    # The cairo renderer is software and needs no driver. setdefault, so anyone
    # debugging a rendering problem can ask for the real one.
    os.environ.setdefault("GSK_RENDERER", "cairo")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

    # No test has any business reading the developer's own passwords.
    #
    # Set to 0 rather than merely cleared. Clearing leaves the default, and the
    # default depends on how gtkpass got onto the path: a checkout is refused,
    # an installed build is not. Since CI now runs this suite against an
    # installed wheel and an installed RPM, clearing would have opened the guard
    # for exactly those runs. Saying 0 outright is the same answer everywhere,
    # and an exported value in the surrounding shell cannot survive it either.
    os.environ["GTKPASS_ALLOW_REAL_STORE"] = "0"

    compiler = shutil.which("glib-compile-schemas")
    if compiler is None:
        return

    target = Path(tempfile.mkdtemp(prefix="gtkpass-schemas-"))
    for xml in SCHEMA_SOURCE_DIR.glob("*.gschema.xml"):
        shutil.copy(xml, target)

    result = subprocess.run(
        [compiler, str(target)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.fail(f"glib-compile-schemas failed:\n{result.stderr}")

    os.environ["GSETTINGS_SCHEMA_DIR"] = str(target)
    COMPILED_SCHEMA_DIR = target


@pytest.fixture(scope="session")
def schema_dir() -> Path:
    """Directory holding the compiled GSettings schema."""
    if COMPILED_SCHEMA_DIR is None:
        pytest.skip("glib-compile-schemas not available")
    return COMPILED_SCHEMA_DIR


# -- git stores ------------------------------------------------------------
#
# Sync is exercised against a bare repository on disk rather than a network
# remote, which makes push, rebase, conflict and non-fast-forward all reachable
# in a unit test with nothing listening on a socket.
#
# scripts/make-dev-store.sh is deliberately not reused here. It generates a GPG
# key, which takes seconds and needs gpg installed; none of the git behaviour
# does, and keeping it that way is why GitStore is a separate object rather than
# something living inside the backends.


def git(*args: str, cwd: Path) -> str:
    """Run git for test setup, failing loudly."""
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.fail(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def init_repo(path: Path) -> Path:
    """A store-shaped git repository with one commit.

    commit.gpgsign is forced off. A developer whose global config signs commits
    would otherwise have every test here block on a pinentry prompt, which under
    pytest looks like a hang rather than a failure.
    """
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-b", "main", cwd=path)
    git("config", "user.email", "test@example.invalid", cwd=path)
    git("config", "user.name", "GTKPass Tests", cwd=path)
    git("config", "commit.gpgsign", "false", cwd=path)
    # The safety guard opens a store carrying this marker without an opt-in.
    (path / ".gtkpass-scratch-store").touch()
    (path / ".gpg-id").write_text("test@example.invalid\n")
    git("add", "-A", cwd=path)
    git("commit", "-m", "Initial", cwd=path)
    return path


@pytest.fixture
def store_repo(tmp_path: Path) -> Path:
    """A git-backed store with no remote."""
    return init_repo(tmp_path / "store")


@pytest.fixture
def bare_remote(tmp_path: Path, store_repo: Path) -> Path:
    """A bare repository on disk, wired up as `origin`."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git("init", "--bare", "-b", "main", cwd=remote)
    git("remote", "add", "origin", str(remote), cwd=store_repo)
    git("push", "-u", "origin", "main", cwd=store_repo)
    return remote


@pytest.fixture
def other_clone(tmp_path: Path, bare_remote: Path) -> Path:
    """A second checkout, for making the remote move ahead."""
    clone = tmp_path / "elsewhere"
    subprocess.run(
        ["git", "clone", str(bare_remote), str(clone)],
        capture_output=True,
        text=True,
        check=True,
    )
    git("config", "user.email", "other@example.invalid", cwd=clone)
    git("config", "user.name", "Somebody Else", cwd=clone)
    git("config", "commit.gpgsign", "false", cwd=clone)
    return clone
