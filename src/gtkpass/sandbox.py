"""What the Flatpak sandbox permits, and how the user can grant more.

Sync reaches a remote over ssh. Inside a sandbox that needs ``--socket=ssh-auth``
and ``--share=network``, which the manifest deliberately does not request: a
password manager should not hold network access and an agent socket on the
chance that someone's store has a remote. The user grants them with ``flatpak
override`` if and when they want sync, so the application has to know whether it
has them, and be able to say exactly what to run when it does not.

The obvious probe is wrong, which is the reason this module exists rather than
an ``os.environ`` lookup at the call site. ``$SSH_AUTH_SOCK`` survives into a
sandbox that was denied the socket: checked against flatpak 1.18.0, running the
packaged application with ``--nosocket=ssh-auth`` leaves the variable pointing at
the host's ``/run/user/$UID/gcr/ssh`` while no such socket exists inside.
Anything trusting it concludes the agent is reachable, and finds out otherwise
by hanging.

``[Context]`` in ``/.flatpak-info`` has neither problem. flatpak-metadata(5)
describes it as the effective configuration, so it already accounts for every
``flatpak override``, and reading it is a file read rather than a subprocess --
which matters, because this decides whether a button is sensitive.

There is no extension-shaped answer to any of this, and it is worth writing down
because it looks like there should be. A Flatpak extension cannot carry
permissions: ``[Extension NAME]`` takes only ``directory``, ``version(s)``,
``add-ld-path``, ``merge-dirs``, ``download-if``/``enable-if``, ``autodelete``,
``no-autodownload`` and ``subdirectories``, and ``[ExtensionOf]`` only ``ref``,
``runtime``, ``priority`` and ``tag``. Neither has a ``[Context]`` group. An
extension is content mounted into a sandbox whose permissions were fixed at
``flatpak build-finish``; it never widens them. Conditional permissions
(``--share-if=``, flatpak 1.17 and later) cover only ``network`` and ``ipc``, and
condition on system capabilities rather than on anything the user chose.
"""

import configparser
import logging
from pathlib import Path

from gtkpass.config import APP_ID

logger = logging.getLogger(__name__)

#: Written by flatpak into every sandbox. Its absence means there is no sandbox.
#: Patched in tests, so it is looked up through the module rather than inlined.
FLATPAK_INFO = Path("/.flatpak-info")

#: Permissions sync needs, in the spelling `flatpak override` accepts.
SYNC_SOCKET = "ssh-auth"
SYNC_PERMISSIONS = (f"--socket={SYNC_SOCKET}", "--share=network")


def is_sandboxed() -> bool:
    """Whether this process is running inside a Flatpak."""
    return FLATPAK_INFO.is_file()


def _context() -> dict[str, set[str]]:
    """The effective ``[Context]`` group, as sets of granted names.

    Returns empty sets rather than raising. This is consulted to decide what to
    offer, and a password manager that will not start because a diagnostic file
    was unreadable is worse than one that offers nothing.
    """
    parser = configparser.ConfigParser()
    try:
        parser.read_string(FLATPAK_INFO.read_text())
    except (OSError, configparser.Error) as error:
        logger.warning("Cannot read %s: %s", FLATPAK_INFO, error)
        return {}

    if not parser.has_section("Context"):
        return {}

    return {
        key: {item for item in value.split(";") if item}
        for key, value in parser["Context"].items()
    }


def has_socket(name: str) -> bool:
    """Whether the sandbox exposes a named socket.

    True outside a sandbox: nothing is being withheld there.
    """
    if not is_sandboxed():
        return True
    return name in _context().get("sockets", set())


def has_network() -> bool:
    """Whether the sandbox shares the host's network."""
    if not is_sandboxed():
        return True
    return "network" in _context().get("shared", set())


def missing_sync_permissions() -> list[str]:
    """Which of the permissions sync needs have not been granted."""
    missing = []
    if not has_socket(SYNC_SOCKET):
        missing.append(f"--socket={SYNC_SOCKET}")
    if not has_network():
        missing.append("--share=network")
    return missing


def override_command() -> str:
    """The command that grants sync the permissions it needs.

    ``--user`` deliberately: the system-wide form needs root and would apply to
    every user on the machine.
    """
    return f"flatpak override --user {' '.join(SYNC_PERMISSIONS)} {APP_ID}"
