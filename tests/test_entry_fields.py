"""How a decrypted entry's lines are split into fields and prose.

Everything below the password is free-form: `pass` prescribes no format, and
what stores actually contain is a mixture of `key: value` lines, bare URIs and
plain sentences. The rule that tells them apart lives in one place because the
detail pane has to agree with it exactly -- a line counted as a field and also
as prose is shown twice, and one counted as neither disappears.
"""

from pathlib import Path

from gtkpass.backends import PasswordEntry, metadata_pair


def entry(content: str) -> PasswordEntry:
    return PasswordEntry(name="site", path=Path("/store/site.gpg"), content=content)


class TestFieldLines:
    def test_a_key_and_value(self):
        assert metadata_pair("username: alice") == ("username", "alice")

    def test_the_key_is_lowercased(self):
        assert metadata_pair("Username: alice") == ("username", "alice")

    def test_a_key_may_contain_spaces(self):
        """The example in passwordstore's own documentation has one."""
        assert metadata_pair("Secret Question 1: my pet") == (
            "secret question 1",
            "my pet",
        )

    def test_a_value_may_contain_colons(self):
        assert metadata_pair("url: https://example.com:8443/x") == (
            "url",
            "https://example.com:8443/x",
        )

    def test_an_empty_value_is_still_a_field(self):
        assert metadata_pair("username:") == ("username", "")

    def test_a_sentence_shaped_like_a_field_is_one(self):
        """The convention gives no way to tell these apart, and does not try.

        A line whose colon is followed by a space is a field, whatever the key
        reads like. Guessing at the key's plausibility would only mean losing
        the fields somebody actually wrote.
        """
        assert metadata_pair("remember: the safe is in the attic") == (
            "remember",
            "the safe is in the attic",
        )


class TestProseLines:
    def test_a_line_without_a_colon(self):
        assert metadata_pair("recovery codes are in the safe") is None

    def test_a_colon_inside_a_word_is_not_a_separator(self):
        """A time, a ratio or a path. None of them names a field."""
        assert metadata_pair("the meeting moved to 10:30") is None

    def test_a_colon_with_no_key(self):
        assert metadata_pair(": stray") is None

    def test_an_empty_line(self):
        assert metadata_pair("   ") is None


class TestUriLines:
    """A bare URI keeps its scheme and its whole self.

    ``otpauth://`` is written on a line of its own by pass-otp, and splitting on
    the first colon turned it into the key ``otpauth`` with the value
    ``//totp/...`` -- a field whose value was no longer the URI it came from.
    Keeping the scheme as the key is what leaves ``otpauth`` recognisable as a
    secret to the detail pane.
    """

    def test_an_otpauth_line_keeps_the_whole_uri(self):
        line = "otpauth://totp/ACME:alice?secret=JBSWY3DPEHPK3PXP"

        assert metadata_pair(line) == ("otpauth", line)

    def test_a_bare_url_keeps_the_whole_uri(self):
        assert metadata_pair("https://example.com/login") == (
            "https",
            "https://example.com/login",
        )

    def test_a_url_inside_a_sentence_is_prose(self):
        assert metadata_pair("see https://example.com for the rest") is None


class TestEntryMetadata:
    def test_fields_are_collected(self):
        parsed = entry("s3cret\nusername: alice\nhost: db.example.com").metadata

        assert parsed == {"username": "alice", "host": "db.example.com"}

    def test_prose_is_not_collected(self):
        parsed = entry("s3cret\nusername: alice\nit is due at 10:30").metadata

        assert parsed == {"username": "alice"}

    def test_the_password_line_is_never_a_field(self):
        """A password may contain a colon, and is not metadata about itself."""
        assert entry("user: pass\nusername: alice").metadata == {"username": "alice"}

    def test_an_otpauth_line_is_kept_whole(self):
        line = "otpauth://totp/ACME:alice?secret=JBSWY3DPEHPK3PXP"

        assert entry(f"s3cret\n{line}").metadata == {"otpauth": line}

    def test_no_content_has_no_fields(self):
        assert PasswordEntry(name="s", path=Path("s")).metadata == {}
