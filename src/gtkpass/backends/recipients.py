"""Who a store's entries are encrypted to, and whether that changed.

``.gpg-id`` decides who can read everything written from now on, and nothing
here verifies it. ``pass`` can sign it -- ``PASSWORD_STORE_SIGNING_KEY`` and a
``.gpg-id.sig`` -- and GTKPass does not, while ``DirectBackend`` encrypts with
``always_trust``, so a key named in that file is simply used.

That was a local question while the store was local. Sync made it a remote one:
whoever can write to the remote can add a recipient, and every entry saved
afterwards is encrypted to them as well.

What they cannot do is re-encrypt the entries that are already there, because
that would mean decrypting them first. That asymmetry is what this module reads.
A recipient set that changed while the entries stayed on the old one is a change
made by somebody who could not read the store -- whereas enrolling a second
machine means re-encrypting to the new set, which shows up as entries that
match.

**This reports; it must never re-encrypt.** Rekeying a store is ``pass init
<ids...>``: a deliberate act by somebody who has decided the new recipient
belongs there. Doing it here, on the strength of the file whose change is under
suspicion, would carry the attack out rather than report it -- it would take
every entry the attacker could not read and hand them a copy they can.

Reading an entry's recipients costs nothing and reveals nothing: ``gpg
--list-only -d`` prints an ENC_TO line per recipient packet and stops before
decrypting, so it needs no passphrase, no secret key, and no agent.
"""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import SUBPROCESS_TIMEOUT_SECONDS, GPGError

logger = logging.getLogger(__name__)

#: The file that names a directory's recipients, as passwordstore defines it.
GPG_ID = ".gpg-id"

#: How the root of a store is written in a record. A name rather than an empty
#: field, so a record stays readable and has no ambiguous line.
ROOT = "."


def read_gpg_id(path: Path) -> tuple[str, ...]:
    """The recipients named in one ``.gpg-id``.

    Comments and blank lines are dropped, and the test is applied to the
    stripped line: ``pass`` does not document comments here, but a store that
    has them must not turn ``  # a note`` into a recipient.
    """
    lines = path.read_text().splitlines()
    return tuple(
        stripped
        for stripped in (line.strip() for line in lines)
        if stripped and not stripped.startswith("#")
    )


def configuration(store_dir: Path) -> dict[str, tuple[str, ...]]:
    """Every ``.gpg-id`` in a store, keyed by the directory it governs.

    Keys are relative POSIX paths so that the answer does not depend on where
    the store is mounted; a store moved between machines has to compare equal to
    itself.
    """
    found = {}
    for gpg_id in sorted(store_dir.rglob(GPG_ID)):
        relative = gpg_id.parent.relative_to(store_dir)
        directory = ROOT if relative == Path() else relative.as_posix()
        recipients = read_gpg_id(gpg_id)
        if recipients:
            found[directory] = recipients
    return found


def record(configuration: dict[str, tuple[str, ...]]) -> str:
    """A canonical string for remembering what was last approved.

    One line per ``.gpg-id``, sorted, so that a reordered file is not mistaken
    for a changed one -- and so the record can be stored as a single setting.
    """
    return "\n".join(
        f"{directory}\t{' '.join(sorted(recipients))}"
        for directory, recipients in sorted(configuration.items())
    )


def parse_record(text: str) -> dict[str, tuple[str, ...]]:
    """Read back what :func:`record` wrote."""
    parsed = {}
    for line in text.splitlines():
        directory, _, joined = line.partition("\t")
        if directory and joined:
            parsed[directory] = tuple(joined.split())
    return parsed


@dataclass(frozen=True)
class RecipientAudit:
    """What a store says about its recipients, against what was approved."""

    #: What the store says now, to be remembered once somebody approves it.
    record: str
    #: Whether that differs from the record it was compared against.
    changed: bool
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    #: Entries not encrypted to the recipients their directory now names.
    stale_entries: tuple[str, ...] = ()
    #: Recipients named in a ``.gpg-id`` with no key in this keyring. Nothing
    #: can be concluded about the entries they govern, and encrypting to them
    #: would fail, so they are reported rather than guessed at.
    unknown_recipients: tuple[str, ...] = ()

    @property
    def suspicious(self) -> bool:
        """Changed, with entries nobody re-encrypted to match.

        The combination is the point. A change on its own is what enrolling a
        machine looks like; a change whose entries were left behind is one made
        by somebody who could not read them.
        """
        return self.changed and bool(self.stale_entries)


def audit(
    store_dir: Path, approved: str = "", gpg_home: Path | None = None
) -> RecipientAudit:
    """Compare a store's recipients with what was last approved.

    An empty ``approved`` is a store being seen for the first time: there is
    nothing for it to have changed from, so it is taken as it stands and
    recorded. Nothing else in GTKPass can establish who *should* be able to read
    somebody's store.

    No gpg runs at all unless the recipients changed, which keeps this on the
    path every backend takes when it is built.

    Raises:
        GPGError: If gpg is needed and cannot be run.
    """
    current = configuration(store_dir)
    now = record(current)

    if not approved or approved == now:
        return RecipientAudit(record=now, changed=False)

    previous = parse_record(approved)
    before = {name for names in previous.values() for name in names}
    after = {name for names in current.values() for name in names}

    stale = []
    unknown = []
    for directory, names in sorted(current.items()):
        if previous.get(directory) == names:
            # This subtree is as it was approved; its entries are not evidence
            # about somebody else's change.
            continue
        expected, missing = _key_ids(names, gpg_home)
        unknown.extend(missing)
        if missing:
            # An incomplete expectation would make every entry under it look
            # stale. The missing key is the finding here.
            continue
        stale.extend(
            _entries_not_encrypted_to(store_dir, directory, expected, gpg_home)
        )

    return RecipientAudit(
        record=now,
        changed=True,
        added=tuple(sorted(after - before)),
        removed=tuple(sorted(before - after)),
        stale_entries=tuple(sorted(stale)),
        unknown_recipients=tuple(sorted(set(unknown))),
    )


def _entries_not_encrypted_to(
    store_dir: Path, directory: str, expected: set[str], gpg_home: Path | None
) -> list[str]:
    """Entry names under ``directory`` whose recipients are not ``expected``.

    Only the entries this ``.gpg-id`` governs: a nested one takes over from
    where it sits, exactly as it does for writing.
    """
    root = store_dir if directory == ROOT else store_dir / directory
    stale = []
    for entry in sorted(root.rglob("*.gpg")):
        relative = entry.relative_to(store_dir)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if _governing_directory(store_dir, entry) != directory:
            continue
        found = _recipients_of(entry, gpg_home)
        if found is None or found == expected:
            continue
        stale.append(relative.as_posix()[: -len(".gpg")])
    return stale


def _governing_directory(store_dir: Path, entry: Path) -> str:
    """Which ``.gpg-id`` applies to an entry: the nearest one above it."""
    directory = entry.parent
    while True:
        if (directory / GPG_ID).is_file():
            relative = directory.relative_to(store_dir)
            return ROOT if relative == Path() else relative.as_posix()
        if directory == store_dir:
            return ROOT
        directory = directory.parent


def _recipients_of(entry: Path, gpg_home: Path | None) -> set[str] | None:
    """The key ids an entry is encrypted to, or None if that cannot be read.

    ``--list-only`` stops before decrypting, so this needs no passphrase and no
    secret key -- and reads nothing of what the entry holds.
    """
    try:
        output = _gpg(["--list-only", "--status-fd", "1", "-d", str(entry)], gpg_home)
    except GPGError as error:
        logger.debug("Cannot read the recipients of %s: %s", entry.name, error)
        return None

    found = set()
    for line in output.splitlines():
        parts = line.split()
        # [GNUPG:] ENC_TO <key id> <algorithm> <integer>
        if len(parts) >= 3 and parts[1] == "ENC_TO":
            found.add(parts[2].upper())
    # An entry encrypted with --throw-keyids says ENC_TO 0000000000000000, which
    # answers nothing; treat it as unreadable rather than as a mismatch.
    if not found or found == {"0" * 16}:
        return None
    return found


def _key_ids(
    names: tuple[str, ...], gpg_home: Path | None
) -> tuple[set[str], list[str]]:
    """Resolve recipients to the key ids gpg would encrypt to, and what it could not.

    Encryption goes to an encryption subkey, which is what ENC_TO names, so the
    primary key's id would never match. Every encryption-capable key belonging to
    the recipient counts: which one gpg picks is its business.
    """
    ids: set[str] = set()
    missing = []
    for name in names:
        try:
            output = _gpg(["--with-colons", "--list-keys", name], gpg_home)
        except GPGError:
            missing.append(name)
            continue
        found = {
            fields[4].upper()
            for fields in (line.split(":") for line in output.splitlines())
            if len(fields) > 11 and fields[0] in {"pub", "sub"} and "e" in fields[11]
        }
        if found:
            ids |= found
        else:
            missing.append(name)
    return ids, missing


def _gpg(arguments: list[str], gpg_home: Path | None) -> str:
    """Run gpg for a question about a file, never for its contents.

    Raises:
        GPGError: If gpg is absent, fails, or does not finish.
    """
    binary = shutil.which("gpg")
    if binary is None:
        raise GPGError("gpg is not installed")

    environment = os.environ.copy()
    # Answers are parsed from this output, and gpg speaks the user's language.
    environment["LC_ALL"] = "C"
    if gpg_home is not None:
        environment["GNUPGHOME"] = str(gpg_home)

    try:
        result = subprocess.run(
            [binary, "--batch", "--no-tty", *arguments],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except OSError as error:
        raise GPGError(f"Could not run gpg: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise GPGError("gpg timed out") from error

    if result.returncode != 0:
        raise GPGError(f"gpg failed: {result.stderr.strip()}")
    return result.stdout
