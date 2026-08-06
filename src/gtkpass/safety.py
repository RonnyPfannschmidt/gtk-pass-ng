"""Keeping real secrets away from development and test runs.

A password manager is read constantly while it is being worked on: probes,
experiments, one-off scripts. Pointed at the developer's own store, those read
real passwords, and whatever they print ends up in a terminal, a CI log or an
AI assistant's transcript.

So the developer's own store is refused unless something deliberately opts in.
``run_app.sh`` does, because that is the application actually being used.
Nothing else should: use a scratch store instead (``make devstore``).
"""

import os
from pathlib import Path

#: Set by run_app.sh. Anything else touching the real store is a mistake.
OPT_IN_VARIABLE = "GTKPASS_ALLOW_REAL_STORE"

DEFAULT_STORE = "~/.password-store"


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


def is_real_store(path: Path) -> bool:
    """Whether ``path`` is one of the user's actual password stores."""
    return _resolve(path) in real_store_paths()


def opted_in() -> bool:
    return os.environ.get(OPT_IN_VARIABLE, "").lower() in {"1", "true", "yes"}


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


def _resolve(path: Path) -> Path:
    """Absolute path, tolerating one that does not exist."""
    try:
        return path.expanduser().resolve()
    except OSError:
        return path.expanduser().absolute()
