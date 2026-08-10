"""Keeping real secrets away from development and test runs.

A password manager is read constantly while it is being worked on: probes,
experiments, one-off scripts. Pointed at the developer's own store, those read
real passwords, and whatever they print ends up in a terminal, a CI log or an
AI assistant's transcript.

So the developer's own store is refused *when the code is running out of a
checkout*, which is where all of that lives. An installed build is the
application actually being used and opens the store as any password manager
would; refusing it there would only mean every packaged build needing a wrapper
to undo this.

``GTKPASS_ALLOW_REAL_STORE`` overrides the decision in both directions, and
``run_app.sh`` sets it to 1 because launching a checkout is the one case where
the checkout really is the application. ``make run-dev`` sets it to 0 and uses a
scratch store (``make devstore``). Nothing else should set it at all.
"""

import functools
import importlib.metadata
import json
import os
from pathlib import Path

#: Overrides the default in both directions. Set to 1 by run_app.sh, and to 0 by
#: `make run-dev`. Anything else reaching for it is a mistake.
OPT_IN_VARIABLE = "GTKPASS_ALLOW_REAL_STORE"

#: The distribution this code belongs to, as installed.
#:
#: Not "gtkpass": that name on PyPI is an unrelated project, and "gtk-pass" was
#: refused as too similar to it, so this is distributed as gtk-pass-ng while the
#: package it installs stays gtkpass. ``importlib.metadata`` normalises
#: separators, so the underscored spelling resolves just as well.
DISTRIBUTION_NAME = "gtk-pass-ng"

#: Metadata directories that live *in* a source tree rather than in an install.
#:
#: setuptools leaves a ``src/gtkpass.egg-info`` behind after a build, and it
#: stays there. It satisfies ``importlib.metadata`` and carries no
#: ``direct_url.json``, so without this a ``PYTHONPATH=src`` run out of a
#: checkout looked exactly like an ordinary packaged install -- and opened the
#: guard on the developer's own store.
SOURCE_TREE_METADATA = (".egg-info", ".egg-link")


class NotInstalled(RuntimeError):
    """Raised when GTKPass is being run without having been installed."""


DEFAULT_STORE = "~/.password-store"

#: Written into a store by ``make devstore``. A store that says outright it was
#: made to be thrown away is not the user's, even when PASSWORD_STORE_DIR points
#: at it -- which is what ``make run-dev`` does. Without this the development
#: launcher had to disable the guard wholesale to open its own scratch store,
#: and then nothing was guarded for the rest of the run.
SCRATCH_MARKER = ".gtkpass-scratch-store"


class RealStoreBlocked(RuntimeError):
    """Raised when code would have read the developer's own password store."""


def default_store_dir() -> Path:
    """Where pass keeps its store when nothing is configured."""
    return Path(os.environ.get("PASSWORD_STORE_DIR") or DEFAULT_STORE).expanduser()


def real_store_paths() -> set[Path]:
    """Stores that hold the user's actual passwords."""
    paths = {Path(DEFAULT_STORE).expanduser()}
    configured = os.environ.get("PASSWORD_STORE_DIR")
    if configured:
        paths.add(Path(configured).expanduser())
    return {_resolve(path) for path in paths}


def is_scratch_store(path: Path) -> bool:
    """Whether ``path`` was created to be thrown away.

    The default store location can never be marked this way: a stray marker
    file in ``~/.password-store`` would otherwise disarm the guard completely.
    """
    if _resolve(path) == _resolve(Path(DEFAULT_STORE)):
        return False
    return (path / SCRATCH_MARKER).exists()


def is_real_store(path: Path) -> bool:
    """Whether ``path`` is one of the user's actual password stores."""
    if is_scratch_store(path):
        return False
    return _resolve(path) in real_store_paths()


def _distributions_named() -> list[importlib.metadata.Distribution]:
    """Every distribution on the path claiming to be this one.

    There can be more than one. ``importlib.metadata`` deduplicates by name, but
    only after normalising it, and a source tree readily offers two spellings at
    once -- a leftover ``src/gtkpass.egg-info`` from before this was renamed
    alongside the current ``src/gtk_pass_ng.egg-info``, both reachable because an
    editable install puts ``src/`` on the path.
    """
    wanted = DISTRIBUTION_NAME.replace("_", "-").lower()
    return [
        dist
        for dist in importlib.metadata.distributions()
        if (dist.metadata["Name"] or "").strip().replace("_", "-").lower() == wanted
    ]


@functools.cache
def _own_distribution() -> importlib.metadata.Distribution | None:
    """The distribution this code belongs to, preferring a real install.

    Cached because the guard asks on every store access and this walks the whole
    path. Anything replacing what it sees has to call ``cache_clear()``.

    A real install is preferred over a source tree's ``.egg-info`` deliberately:
    with both present the answer would otherwise depend on which
    ``importlib.metadata`` reached first, and that decides whether the
    application starts at all.
    """
    found = None
    for dist in _distributions_named():
        if not _from_source_tree_metadata(dist):
            return dist
        found = found or dist
    return found


def _from_source_tree_metadata(dist: importlib.metadata.Distribution) -> bool:
    """Whether ``dist`` is a build artefact in a source tree, not an install.

    Reads the private ``_path`` that ``PathDistribution`` carries, there being
    no public way to ask where metadata was found. It is absent on other
    distribution types, which are not what this is looking for anyway.
    """
    path = getattr(dist, "_path", None)
    if path is None:
        return False
    return Path(str(path)).suffix in SOURCE_TREE_METADATA


def require_installed() -> None:
    """Refuse to run from a source tree that was never installed.

    ``PYTHONPATH=src python -m gtkpass`` gives a process nothing can be
    established about -- not its version, and not whether it is somebody's
    working copy. Guessing about that is what the guard exists to avoid, so this
    fails at import and says what to do instead.

    Raises:
        NotInstalled: If nothing describes this code as installed.
    """
    dist = _own_distribution()
    if dist is not None and not _from_source_tree_metadata(dist):
        return
    found = "" if dist is None else " Only a source tree's .egg-info was found."
    raise NotInstalled(
        f"GTKPass is not installed, so it will not run.\n"
        f"Nothing describes this code as an installed {DISTRIBUTION_NAME!r} "
        f"distribution, which is what happens when it is put on PYTHONPATH "
        f"instead.{found}\n"
        f"Run 'make sync' for a development install, or install a package."
    )


def _editable_per_metadata(dist: importlib.metadata.Distribution) -> bool | None:
    """Whether the distribution records an editable install.

    Returns None when the metadata does not answer, which the caller treats the
    same way as yes: an unreadable answer is not a licence to open the guard.
    """
    recorded = dist.read_text("direct_url.json")
    if recorded is None:
        # No direct_url.json: installed from an index or by a package manager,
        # which is as ordinary an install as there is. PEP 610.
        return False
    try:
        return bool(json.loads(recorded).get("dir_info", {}).get("editable", False))
    except (ValueError, AttributeError):
        return None


def _describes(dist: importlib.metadata.Distribution, package_dir: Path) -> bool:
    """Whether ``dist`` is the metadata for the code actually running."""
    try:
        base = Path(str(dist.locate_file(""))).resolve()
    except OSError:
        return False
    return package_dir.is_relative_to(base)


def running_from_checkout(module_file: Path | str | None = None) -> bool:
    """Whether this code is being run out of a source tree.

    Asked of the installed distribution, because an editable install says so
    outright -- ``direct_url.json`` carries ``dir_info.editable``, which pip and
    uv both write and which is the only signal that means it rather than
    resembling it.

    The metadata is believed only when it describes the module that is running.
    A checkout ahead of a released copy on ``sys.path`` would otherwise be
    called an installed build on the strength of the installed copy's metadata,
    while the code executing is the working copy -- the one case where being
    wrong opens the guard rather than closing it.
    """
    package_dir = Path(module_file or __file__).resolve().parent

    dist = _own_distribution()
    if dist is None or _from_source_tree_metadata(dist):
        # require_installed() normally stops both of these at import; anything
        # reaching here has established nothing about what is running.
        return True

    editable = _editable_per_metadata(dist)
    if editable is None or editable:
        return True

    return not _describes(dist, package_dir)


def opted_in() -> bool:
    """Whether reading the user's own store and keyring is allowed.

    The environment variable decides when it says anything; otherwise an
    installed build is allowed and a checkout is not.
    """
    configured = os.environ.get(OPT_IN_VARIABLE, "")
    if configured:
        return configured.lower() in {"1", "true", "yes"}
    return not running_from_checkout()


def ensure_store_allowed(path: Path) -> None:
    """Refuse the user's own store unless something opted in.

    Raises:
        RealStoreBlocked: If this would read real passwords.
    """
    if not is_real_store(path) or opted_in():
        return
    raise RealStoreBlocked(
        f"Refusing to open the real password store at {path}.\n"
        f"Development and test code should use a scratch store; run "
        f"'make devstore' for one.\n"
        f"If this really is the application being used, set "
        f"{OPT_IN_VARIABLE}=1 (run_app.sh already does)."
    )


def ensure_keyring_allowed() -> None:
    """Refuse the user's keyring unless something opted in.

    There is no scratch equivalent here: the Secret Service is whichever one the
    session bus offers, so the only safe assumption is that it is the real one.
    A private bus -- what ``make test`` runs under -- simply has no service to
    reach, which is a separate and weaker protection than this.

    Raises:
        RealStoreBlocked: If this would read real secrets.
    """
    if opted_in():
        return
    raise RealStoreBlocked(
        "Refusing to open the session keyring.\n"
        "Development and test code has no business reading it; it holds the "
        "user's real secrets and unlocking it may prompt them.\n"
        f"If this really is the application being used, set "
        f"{OPT_IN_VARIABLE}=1 (run_app.sh already does)."
    )


def _resolve(path: Path) -> Path:
    """Absolute path, tolerating one that does not exist."""
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()
