"""One-time codes: reading an ``otpauth://`` line and turning it into digits."""

import base64

import pytest

from gtkpass.otp import (
    OTPError,
    code_at,
    format_code,
    otpauth_line,
    parse_otpauth,
    seconds_remaining,
)

#: The shared secret every RFC 6238 test vector uses, as an otpauth URI carries
#: it. The RFC gives it as the ASCII string; base32 is the transport.
RFC_SECRET = b"12345678901234567890"


def rfc_uri(algorithm: str = "SHA1", digits: int = 8) -> str:
    """An otpauth URI over the RFC's secret, extended to the wider hashes.

    The RFC seeds SHA256 and SHA512 with the same ASCII digits repeated to the
    hash's block size, which is what the longer secrets below are.
    """
    seed = {"SHA1": 20, "SHA256": 32, "SHA512": 64}[algorithm]
    secret = (RFC_SECRET * 4)[:seed]
    encoded = base64.b32encode(secret).decode()
    return (
        f"otpauth://totp/Example:alice@example.com?secret={encoded}"
        f"&issuer=Example&algorithm={algorithm}&digits={digits}"
    )


class TestRFC6238Vectors:
    """The arithmetic, against the vectors in RFC 6238 Appendix B.

    Here rather than a round-trip against our own implementation because the
    point of a one-time code is that somebody else's server computes the same
    number from the same secret.
    """

    @pytest.mark.parametrize(
        ("when", "expected"),
        [
            (59, "94287082"),
            (1111111109, "07081804"),
            (1111111111, "14050471"),
            (1234567890, "89005924"),
            (2000000000, "69279037"),
            (20000000000, "65353130"),
        ],
    )
    def test_sha1(self, when, expected):
        assert code_at(parse_otpauth(rfc_uri()), when) == expected

    @pytest.mark.parametrize(
        ("algorithm", "expected"),
        [("SHA256", "46119246"), ("SHA512", "90693936")],
    )
    def test_the_wider_hashes(self, algorithm, expected):
        assert code_at(parse_otpauth(rfc_uri(algorithm)), 59) == expected

    def test_a_code_is_padded_to_its_width(self):
        """07081804 leads with a zero, and a bare int would have dropped it."""
        assert code_at(parse_otpauth(rfc_uri()), 1111111109).startswith("0")


class TestParsing:
    def test_the_defaults_are_the_ones_the_spec_names(self):
        """Six digits, thirty seconds, SHA1 -- what a URI that says nothing means."""
        params = parse_otpauth("otpauth://totp/alice?secret=JBSWY3DPEHPK3PXP")

        assert (params.digits, params.period, params.algorithm) == (6, 30, "SHA1")

    def test_the_label_carries_the_issuer_and_the_account(self):
        params = parse_otpauth(
            "otpauth://totp/Example:alice@example.com?secret=JBSWY3DPEHPK3PXP"
        )

        assert (params.issuer, params.account) == ("Example", "alice@example.com")

    def test_the_issuer_parameter_wins_over_the_label(self):
        """Both spellings exist and the parameter is the authoritative one."""
        params = parse_otpauth(
            "otpauth://totp/Old:alice?secret=JBSWY3DPEHPK3PXP&issuer=New"
        )

        assert params.issuer == "New"

    def test_a_percent_encoded_label_is_decoded(self):
        params = parse_otpauth(
            "otpauth://totp/ACME%20Co:alice%40example.com?secret=JBSWY3DPEHPK3PXP"
        )

        assert (params.issuer, params.account) == ("ACME Co", "alice@example.com")

    def test_a_secret_written_in_groups_is_still_a_secret(self):
        """Sites print the base32 in spaced groups and people paste what they see."""
        spaced = parse_otpauth("otpauth://totp/a?secret=jbsw y3dp ehpk 3pxp")
        tight = parse_otpauth("otpauth://totp/a?secret=JBSWY3DPEHPK3PXP")

        assert spaced.secret == tight.secret

    def test_an_unpadded_secret_is_accepted(self):
        """base64.b32decode refuses what every authenticator emits."""
        assert parse_otpauth("otpauth://totp/a?secret=JBSWY3DPEHPK3PX").secret

    def test_the_parameters_do_not_repr_the_secret(self):
        """As PasswordEntry does not: a repr reaches logs and assertion diffs."""
        params = parse_otpauth("otpauth://totp/a?secret=JBSWY3DPEHPK3PXP")

        assert "JBSWY3DPEHPK3PXP" not in repr(params)
        assert str(params.secret) not in repr(params)

    @pytest.mark.parametrize(
        ("uri", "because"),
        [
            ("https://example.com/", "not an otpauth URI at all"),
            ("otpauth://totp/a", "no secret"),
            ("otpauth://totp/a?secret=", "an empty secret"),
            ("otpauth://totp/a?secret=not-base32!", "a secret that is not base32"),
            ("otpauth://hotp/a?secret=JBSWY3DPEHPK3PXP&counter=1", "counter based"),
            ("otpauth://vtotp/a?secret=JBSWY3DPEHPK3PXP", "an unknown type"),
            (
                "otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&algorithm=MD5",
                "an unknown hash",
            ),
            ("otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&digits=2", "too few digits"),
            ("otpauth://totp/a?secret=JBSWY3DPEHPK3PXP&period=0", "a period of zero"),
        ],
    )
    def test_what_cannot_produce_codes_is_refused(self, uri, because):
        with pytest.raises(OTPError):
            parse_otpauth(uri)

    def test_the_counter_based_refusal_says_which_one_it_is(self):
        """HOTP is a real otpauth URI we do not do, not a malformed one."""
        with pytest.raises(OTPError, match=r"(?i)counter"):
            parse_otpauth("otpauth://hotp/a?secret=JBSWY3DPEHPK3PXP&counter=1")


class TestCountdown:
    def test_a_fresh_code_has_its_whole_period(self):
        params = parse_otpauth("otpauth://totp/a?secret=JBSWY3DPEHPK3PXP")

        assert seconds_remaining(params, 1800.0) == 30

    def test_the_last_second_is_reported_as_one_not_zero(self):
        """Rounding down showed 0 for a whole second, which reads as expired."""
        params = parse_otpauth("otpauth://totp/a?secret=JBSWY3DPEHPK3PXP")

        assert seconds_remaining(params, 1829.5) == 1


class TestFindingTheLine:
    def test_the_uri_is_found_whatever_key_it_came_in_under(self):
        """pass-otp writes it bare, so metadata_pair keys it by its scheme."""
        uri = "otpauth://totp/a?secret=JBSWY3DPEHPK3PXP"

        assert otpauth_line({"username": "alice", "otpauth": uri}) == uri

    def test_an_entry_without_one_has_none(self):
        assert otpauth_line({"username": "alice"}) is None


class TestFormatting:
    @pytest.mark.parametrize(
        ("code", "shown"),
        [("123456", "123 456"), ("12345678", "1234 5678"), ("1234567", "1234567")],
    )
    def test_codes_are_grouped_so_they_can_be_read_off(self, code, shown):
        assert format_code(code) == shown


def test_the_parameters_are_a_value():
    """Frozen: nothing holding one may change what codes it produces.

    mypy already knows, which is why the assignment is ignored rather than
    written differently -- the test is here for the day somebody takes
    ``frozen=True`` off and the type checker stops knowing.
    """
    params = parse_otpauth("otpauth://totp/a?secret=JBSWY3DPEHPK3PXP")

    with pytest.raises(AttributeError):
        params.period = 60  # type: ignore[misc]
