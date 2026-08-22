"""What the Flatpak sandbox permits, and how the user can grant more.

Sync reaches a remote over ssh. Inside a sandbox that needs ``--socket=ssh-auth``
and ``--share=network``, which the manifest deliberately does not request: a
password manager should not hold network access and an agent socket on the
chance that someone's store has a remote. The user grants them with ``flatpak
override`` if and when they want sync, so the application has to know whether it
has them, and be able to say exactly what to run when it does not.

An ssh remote needs two files out of ``~/.ssh`` on top of those, granted one
file at a time so that no private key comes with them -- see ``SSH_FILES``. They
are asked for separately because they are needed by ssh rather than by syncing:
an https remote wants neither.

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
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from gtkpass.config import APP_ID

logger = logging.getLogger(__name__)

#: Written by flatpak into every sandbox. Its absence means there is no sandbox.
#: Patched in tests, so it is looked up through the module rather than inlined.
FLATPAK_INFO = Path("/.flatpak-info")

#: Permissions sync needs, in the spelling `flatpak override` accepts.
SYNC_SOCKET = "ssh-auth"
SYNC_PERMISSIONS = (f"--socket={SYNC_SOCKET}", "--share=network")

#: The two files out of ``~/.ssh`` that an ssh remote cannot do without, and
#: the only two this ever names.
#:
#: ``config`` is where ``Host`` aliases live. A remote written as
#: ``git@store:me/store.git`` is not a hostname at all until that file has been
#: read, so a sandbox without it fails with *"Could not resolve hostname
#: store"* -- a DNS-shaped error with a permissions-shaped cause, which is why
#: ``GitStore.explain`` translates it rather than passing it on.
#:
#: ``known_hosts`` is the other half. ``GitStore`` pins
#: ``StrictHostKeyChecking=yes``, so without it every ssh remote stops at host
#: key verification instead, and accepting the key on the *host* changes
#: nothing inside.
#:
#: Granted per file, never as ``--filesystem=~/.ssh:ro``. That directory mixes
#: the private keys in with these two, there is no narrower spelling of it, and
#: handing a password manager every key on the machine to resolve a hostname is
#: not a trade worth making. ``flatpak --filesystem`` takes a file path, so it
#: does not have to be: checked against flatpak 1.18.0, a sandbox granted these
#: two sees a ``~/.ssh`` containing exactly them.
#:
#: Read-only because ssh has no reason to write either. In batch mode with
#: strict checking it never appends to ``known_hosts``, and it never writes
#: ``config`` at all.
SSH_CONFIG = "~/.ssh/config"
SSH_KNOWN_HOSTS = "~/.ssh/known_hosts"
SSH_FILES = (SSH_CONFIG, SSH_KNOWN_HOSTS)
SSH_FILE_PERMISSIONS = tuple(f"--filesystem={path}:ro" for path in SSH_FILES)

#: git's own configuration directory on the host, and the grant that mounts it.
#:
#: Unlike the ssh files this one *is* in the manifest, because what it fixes is
#: not an opt-in feature. git refuses to commit without an author identity, and
#: inside a sandbox it has none: flatpak points ``$XDG_CONFIG_HOME`` at
#: ``~/.var/app/$FLATPAK_ID/config``, so the host's ``~/.config/git`` is not
#: what git reads. Every write to a git-backed store commits, so without this
#: the application fails on save rather than on some feature nobody turned on.
#:
#: ``xdg-config/git`` rather than ``~/.gitconfig``: flatpak mounts this one at
#: both the host path and the app's redirected XDG directory, so an
#: ``includeIf gitdir:`` chain whose paths are written ``~/.config/git/...``
#: still resolves. Checked against flatpak 1.18.0 -- granting ``~/.gitconfig``
#: alone mounts that file and leaves those includes dangling.
#:
#: Still worth checking at runtime, because a manifest grant can be taken away
#: with ``--nofilesystem`` and the failure then looks identical.
GIT_CONFIG = "xdg-config/git"
GIT_CONFIG_PERMISSION = f"--filesystem={GIT_CONFIG}:ro"

#: What flatpak appends to a filesystem entry to say how it is mounted. Stripped
#: before comparing paths, because the grant and the need are the same file
#: whether it was mounted :ro or :create.
_FILESYSTEM_MODES = frozenset({"ro", "rw", "create"})

#: Grants that cover everything underneath them, so nothing narrower needs
#: asking for. ``host`` is the whole filesystem; ``home`` is all of ``~``.
_BLANKET_FILESYSTEMS = frozenset({"host", "home"})


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


def has_filesystem(path: str) -> bool:
    """Whether the sandbox can read a path, directly or through a wider grant.

    True outside a sandbox: nothing is being withheld there.

    A grant on a parent counts. Somebody who already opened all of ``~/.ssh``,
    or all of ``home``, has answered the question, and telling them to grant
    something they have would send them looking for a fault that is not there.
    Compared as paths rather than as strings, because a prefix test on the text
    reads ``~/.ssh-backup`` as covering ``~/.ssh``.
    """
    if not is_sandboxed():
        return True

    wanted = PurePosixPath(path)
    for entry in _context().get("filesystems", set()):
        if entry.startswith("!"):
            # A revocation. flatpak writes these for --nofilesystem, and
            # reading one as a grant would invert its meaning.
            continue
        head, separator, mode = entry.rpartition(":")
        granted = head if separator and mode in _FILESYSTEM_MODES else entry
        if granted in _BLANKET_FILESYSTEMS:
            return True
        granted_path = PurePosixPath(granted)
        if granted_path == wanted or granted_path in wanted.parents:
            return True
    return False


def missing_ssh_file_permissions() -> list[str]:
    """Which of the ``~/.ssh`` files an ssh remote needs are not readable.

    In manifest order, so the command built out of it is stable: advice that
    reshuffles itself between two runs looks like different advice.
    """
    return [f"--filesystem={path}:ro" for path in SSH_FILES if not has_filesystem(path)]


def missing_sync_permissions() -> list[str]:
    """Which of the permissions sync needs have not been granted."""
    missing = []
    if not has_socket(SYNC_SOCKET):
        missing.append(f"--socket={SYNC_SOCKET}")
    if not has_network():
        missing.append("--share=network")
    return missing


def override_command(permissions: "Sequence[str]" = SYNC_PERMISSIONS) -> str:
    """The command that grants this application a set of permissions.

    Defaults to what sync needs, which is the case it was written for; the
    ``~/.ssh`` files are asked for separately, because they are needed by an
    ssh remote rather than by syncing as such and an https one wants neither.

    ``--user`` deliberately: the system-wide form needs root and would apply to
    every user on the machine.
    """
    return f"flatpak override --user {' '.join(permissions)} {APP_ID}"
