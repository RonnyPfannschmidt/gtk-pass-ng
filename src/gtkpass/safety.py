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

import os
from pathlib import Path

#: Overrides the default in both directions. Set to 1 by run_app.sh, and to 0 by
#: `make run-dev`. Anything else reaching for it is a mistake.
OPT_IN_VARIABLE = "GTKPASS_ALLOW_REAL_STORE"

#: A source tree has one of these above the package; an installed one does not.
CHECKOUT_MARKER = "pyproject.toml"

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


def running_from_checkout(module_file: Path | str | None = None) -> bool:
    """Whether this code is being run out of a source tree.

    Decided by looking for a ``pyproject.toml`` above the package rather than by
    asking ``importlib.metadata``, because the answer has to cover three cases
    with one rule: an editable install, whose module files stay in the checkout;
    a plain ``PYTHONPATH=src`` run, which has no distribution metadata at all;
    and a checkout that also has a released copy installed system-wide, where
    the metadata describes the copy that is *not* running.

    In every one of those the module sits inside the tree, one or two levels
    below its ``pyproject.toml`` -- ``src/gtkpass/`` or a flat ``gtkpass/``. An
    installed package sits in ``site-packages`` with no such file above it.
    """
    here = Path(module_file or __file__).resolve()
    return any((parent / CHECKOUT_MARKER).exists() for parent in here.parents[1:3])


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
