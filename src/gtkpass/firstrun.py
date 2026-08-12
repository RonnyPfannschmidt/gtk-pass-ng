"""What GTKPass can work out for itself before anybody configures it.

The first-run screen used to hand the user a preferences dialog with a combo
box of four backend type names and no way to tell which one they wanted. The
overwhelmingly common case -- somebody who already uses `pass` and wants a
window onto it -- can be recognised instead: the store is where `pass` puts it,
and it says so by carrying a `.gpg-id`.

Nothing here reads an entry. It looks at a directory and at one file's
existence, which is what tells a password store apart from a directory that
happens to be called one.
"""

import logging
import shutil
from pathlib import Path

from gtkpass.safety import default_store_dir, ensure_store_allowed

logger = logging.getLogger(__name__)

#: What every passwordstore-format store has at its root: the recipients its
#: entries are encrypted to. A directory without one is not a store, however it
#: is named.
STORE_MARKER = ".gpg-id"


def existing_store() -> Path | None:
    """The store `pass` would use, if there is one and it may be opened.

    Returns None when there is nothing there, when what is there is not a
    store, or when this build is not allowed to open it -- a checkout is not,
    and offering a button that cannot work is worse than offering nothing.
    """
    store = default_store_dir()
    if not (store / STORE_MARKER).is_file():
        return None

    try:
        ensure_store_allowed(store)
    except Exception as e:
        # Running out of a checkout. The guard is doing its job; this is not a
        # failure to report, it is a button not to offer.
        logger.debug("Not offering the store at %s: %s", store, e)
        return None
    return store


def backend_type_for(store: Path) -> str:
    """Which backend to open a passwordstore-format store with.

    `pass` when it is installed, because a store it manages keeps working the
    way its owner is used to -- extensions, hooks, its own git handling. The
    native GPG backend otherwise, which needs nothing on PATH and reads the
    same layout.
    """
    return "pass" if shutil.which("pass") else "direct"
