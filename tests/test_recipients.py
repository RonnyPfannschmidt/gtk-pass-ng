"""Reading who a store is encrypted to, and noticing when that changed.

`.gpg-id` decides who can read everything written from here on, and nothing
verifies it. That was a local question while the store was local; sync made it a
remote one.

The asymmetry these tests are built around: whoever can write to a remote can
add a recipient, but cannot re-encrypt the existing entries to it, because that
would mean decrypting them first. So a recipient set that changed while the
entries stayed on the old one is a change nobody with the keys made.
"""

import shutil
import subprocess

import pytest

from gtkpass.backends import recipients

pytestmark = pytest.mark.requires_gpg

FIRST = "gtkpass-first@example.invalid"
SECOND = "gtkpass-second@example.invalid"


def generate(home, identity):
    result = subprocess.run(
        [
            "gpg",
            "--batch",
            "--pinentry-mode",
            "loopback",
            "--passphrase",
            "",
            "--quick-generate-key",
            f"GTKPass Test <{identity}>",
            "default",
            "default",
            "never",
        ],
        env={"GNUPGHOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"could not generate a test key: {result.stderr}")


@pytest.fixture(scope="session")
def gpg_home(tmp_path_factory):
    """A throwaway GPG home holding two usable keys."""
    if shutil.which("gpg") is None:
        pytest.skip("gpg is not installed")

    home = tmp_path_factory.mktemp("gnupg-recipients")
    home.chmod(0o700)
    generate(home, FIRST)
    generate(home, SECOND)
    return home


@pytest.fixture
def store(tmp_path, gpg_home):
    """A store encrypted to FIRST, with one entry in it."""
    root = tmp_path / "store"
    root.mkdir()
    (root / f"{recipients.GPG_ID}").write_text(f"{FIRST}\n")
    encrypt(root / "email.gpg", [FIRST], gpg_home)
    return root


def encrypt(path, identities, gpg_home):
    """Write a .gpg file encrypted to the given recipients."""
    path.parent.mkdir(parents=True, exist_ok=True)
    arguments = ["gpg", "--batch", "--yes", "--trust-model", "always", "-e"]
    for identity in identities:
        arguments += ["-r", identity]
    arguments += ["-o", str(path)]
    result = subprocess.run(
        arguments,
        input=b"hunter2\n",
        env={"GNUPGHOME": str(gpg_home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


class TestReadingTheConfiguration:
    def test_the_root_recipients_are_found(self, store):
        assert recipients.configuration(store) == {".": (FIRST,)}

    def test_comments_and_blank_lines_are_dropped(self, store):
        (store / recipients.GPG_ID).write_text(f"# who can read this\n\n  {FIRST}  \n")

        assert recipients.configuration(store) == {".": (FIRST,)}

    def test_a_delegated_subtree_is_kept_separate(self, store):
        (store / "work").mkdir()
        (store / "work" / recipients.GPG_ID).write_text(f"{FIRST}\n{SECOND}\n")

        assert recipients.configuration(store) == {
            ".": (FIRST,),
            "work": (FIRST, SECOND),
        }

    def test_the_record_survives_the_store_being_moved(self, store, tmp_path):
        before = recipients.record(recipients.configuration(store))
        moved = tmp_path / "somewhere-else"
        shutil.move(store, moved)

        assert recipients.record(recipients.configuration(moved)) == before

    def test_a_record_reads_back_as_what_it_recorded(self, store):
        configuration = recipients.configuration(store)

        assert (
            recipients.parse_record(recipients.record(configuration)) == configuration
        )


class TestNothingToReport:
    def test_a_store_seen_for_the_first_time_is_taken_as_it_is(self, store, gpg_home):
        """Trust on first use: there is nothing to have changed from."""
        result = recipients.audit(store, approved="", gpg_home=gpg_home)

        assert not result.changed
        assert not result.suspicious
        assert result.record == recipients.record(recipients.configuration(store))

    def test_an_unchanged_store_reports_nothing(self, store, gpg_home):
        approved = recipients.record(recipients.configuration(store))

        result = recipients.audit(store, approved=approved, gpg_home=gpg_home)

        assert not result.changed
        assert result.stale_entries == ()


class TestARecipientAppears:
    @pytest.fixture
    def approved(self, store):
        return recipients.record(recipients.configuration(store))

    def test_an_addition_nobody_re_encrypted_for_is_suspicious(
        self, store, approved, gpg_home
    ):
        """The shape of the attack: the file changed, the entries did not."""
        (store / recipients.GPG_ID).write_text(f"{FIRST}\n{SECOND}\n")

        result = recipients.audit(store, approved=approved, gpg_home=gpg_home)

        assert result.changed
        assert result.added == (SECOND,)
        assert result.stale_entries == ("email",)
        assert result.suspicious

    def test_an_addition_with_the_rekey_that_belongs_with_it_is_not(
        self, store, approved, gpg_home
    ):
        """What enrolling a second machine actually looks like."""
        (store / recipients.GPG_ID).write_text(f"{FIRST}\n{SECOND}\n")
        encrypt(store / "email.gpg", [FIRST, SECOND], gpg_home)

        result = recipients.audit(store, approved=approved, gpg_home=gpg_home)

        assert result.changed
        assert result.added == (SECOND,)
        assert result.stale_entries == ()
        assert not result.suspicious

    def test_a_recipient_with_no_key_here_is_named(self, store, approved, gpg_home):
        """Nothing can be concluded about entries, and that is worth saying.

        A key that is not in the keyring cannot be encrypted to either, so this
        is a store whose next write would fail -- for a reason worth reporting
        as itself rather than as an encryption error later.
        """
        (store / recipients.GPG_ID).write_text(f"{FIRST}\nstranger@example.invalid\n")

        result = recipients.audit(store, approved=approved, gpg_home=gpg_home)

        assert result.changed
        assert result.unknown_recipients == ("stranger@example.invalid",)
        assert result.stale_entries == ()

    def test_a_removal_leaves_the_old_reader_able_to_read(
        self, store, approved, gpg_home
    ):
        """Dropping someone from .gpg-id does not take back what they have.

        Every entry is still encrypted to them until it is rewritten, which is
        the same staleness seen from the other side.
        """
        (store / recipients.GPG_ID).write_text(f"{FIRST}\n{SECOND}\n")
        encrypt(store / "email.gpg", [FIRST, SECOND], gpg_home)
        approved = recipients.record(recipients.configuration(store))
        (store / recipients.GPG_ID).write_text(f"{FIRST}\n")

        result = recipients.audit(store, approved=approved, gpg_home=gpg_home)

        assert result.removed == (SECOND,)
        assert result.stale_entries == ("email",)

    def test_a_delegated_subtree_is_audited_against_its_own_file(self, store, gpg_home):
        (store / "work").mkdir()
        (store / "work" / recipients.GPG_ID).write_text(f"{FIRST}\n")
        encrypt(store / "work" / "mail.gpg", [FIRST], gpg_home)
        approved = recipients.record(recipients.configuration(store))
        (store / "work" / recipients.GPG_ID).write_text(f"{FIRST}\n{SECOND}\n")

        result = recipients.audit(store, approved=approved, gpg_home=gpg_home)

        assert result.stale_entries == ("work/mail",)
        assert "email" not in result.stale_entries, "the root subtree is unaffected"
