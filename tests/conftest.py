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

    # No test has any business reading the developer's own passwords. Clearing
    # this rather than merely not setting it means an exported value in the
    # surrounding shell cannot quietly re-enable it for the whole run.
    os.environ.pop("GTKPASS_ALLOW_REAL_STORE", None)

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
