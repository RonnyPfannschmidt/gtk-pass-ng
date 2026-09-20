"""One-time codes, read off the ``otpauth://`` line an entry already carries.

`pass-otp` stores a TOTP secret as a whole ``otpauth://`` URI on a line of its
own, and that is the format this reads and the only one it writes back --
nothing here edits an entry, so a store stays usable from `pass` and from here
at the same time.

RFC 6238 over :mod:`hmac` rather than a dependency. The specification is a
counter derived from the clock, an HMAC over it and a truncation, which is the
function below; `pyotp` would have been a package to audit and pin for twenty
lines of arithmetic that has not changed since 2011.

Scanning a QR code is not here and is not planned: that is a camera, an image
decoder and two more dependencies, and none of them are needed to read a
secret a store already holds.
"""

import base64
import binascii
import hashlib
import hmac
import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlsplit

#: The hashes an otpauth URI may name, by the spelling it names them with.
#:
#: Almost every site uses SHA1, which is not a weakness here: HOTP's security
#: rests on HMAC, and HMAC-SHA1 is not affected by the collision attacks that
#: retired SHA1 for signatures.
ALGORITHMS = {
    "SHA1": hashlib.sha1,
    "SHA256": hashlib.sha256,
    "SHA512": hashlib.sha512,
}

#: How many digits a code may have. Six is universal, eight is specified and
#: occasionally used; outside that range a server is not going to agree with us
#: and a code that cannot work is worse than a row that says why.
DIGIT_RANGE = range(6, 11)

#: The URI prefix a line has to start with to be one of these at all.
OTPAUTH_PREFIX = "otpauth://"


class OTPError(ValueError):
    """An ``otpauth://`` line that cannot produce codes.

    Carried to the interface and shown, rather than swallowed. An entry whose
    OTP line is malformed has a real problem its owner wants to know about, and
    a row that quietly fails to appear says nothing about it.
    """


@dataclass(frozen=True)
class OTPParameters:
    """Everything the arithmetic needs, taken off one otpauth URI.

    Frozen because the codes it produces are a function of it: something that
    could change a period underneath a countdown would be showing one number
    and counting down another.
    """

    #: The shared secret, decoded. Excluded from the generated repr for the
    #: reason PasswordEntry.content is: a repr reaches log lines, tracebacks
    #: and pytest assertion diffs, and this is the seed of every future code.
    secret: bytes = field(repr=False)
    digits: int = 6
    period: int = 30
    algorithm: str = "SHA1"
    issuer: str = ""
    account: str = ""

    def __repr__(self) -> str:
        """Identify the parameters without disclosing the secret."""
        return (
            f"OTPParameters(issuer={self.issuer!r}, account={self.account!r}, "
            f"{self.algorithm}, digits={self.digits}, period={self.period})"
        )


def parse_otpauth(uri: str) -> OTPParameters:
    """Read one ``otpauth://`` URI.

    Args:
        uri: The line as the store wrote it.

    Returns:
        The parameters its codes come from.

    Raises:
        OTPError: If it is not an otpauth URI, names something other than
            TOTP, or leaves out anything the arithmetic needs.
    """
    parts = urlsplit(uri.strip())
    if parts.scheme.lower() != "otpauth":
        raise OTPError("Not an otpauth:// URI")

    kind = parts.netloc.lower()
    if kind == "hotp":
        # A real otpauth URI we deliberately do not do. Every code advances a
        # counter that has to be written back into the entry, so showing one
        # without writing would hand out a code the server has already seen.
        raise OTPError("Counter-based (HOTP) codes are not supported")
    if kind != "totp":
        raise OTPError(f"Unknown one-time code type '{parts.netloc}'")

    query = parse_qs(parts.query)
    secret = _decode_secret(_one(query, "secret"))

    algorithm = (_one(query, "algorithm") or "SHA1").upper()
    if algorithm not in ALGORITHMS:
        raise OTPError(f"Unknown hash '{algorithm}'")

    digits = _number(query, "digits", 6)
    if digits not in DIGIT_RANGE:
        raise OTPError(f"A code of {digits} digits is not one any server issues")

    period = _number(query, "period", 30)
    if period <= 0:
        raise OTPError("A code has to last longer than no time at all")

    issuer, account = _label(parts.path)
    return OTPParameters(
        secret=secret,
        digits=digits,
        period=period,
        algorithm=algorithm,
        issuer=_one(query, "issuer") or issuer,
        account=account,
    )


def code_at(params: OTPParameters, when: float) -> str:
    """The code that is valid at ``when``, as a Unix time.

    RFC 6238 is RFC 4226 with the counter read off the clock, so this is the
    HOTP truncation over ``when // period``.
    """
    counter = int(when // params.period)
    digest = hmac.new(
        params.secret, struct.pack(">Q", counter), ALGORITHMS[params.algorithm]
    ).digest()
    # Dynamic truncation, RFC 4226 section 5.3: the low nibble of the last byte
    # picks where in the digest to read the code from, so every byte of it has
    # a chance to matter.
    offset = digest[-1] & 0x0F
    (chunk,) = struct.unpack(">I", digest[offset : offset + 4])
    # Zero-padded, because the leading zeros are part of the code: 07081804 is
    # not 7081804, and an int would have dropped the difference silently.
    return str((chunk & 0x7FFFFFFF) % 10**params.digits).zfill(params.digits)


def seconds_remaining(params: OTPParameters, when: float) -> int:
    """How long the code valid at ``when`` has left, rounded up.

    Rounded up so the last fraction of a second reads as 1 rather than 0: a
    countdown that sits on zero looks like a code that has already expired
    while it is still the one to type.
    """
    return math.ceil(params.period - (when % params.period)) or params.period


def format_code(code: str) -> str:
    """Group a code so it can be read off the screen and typed.

    Every authenticator does this, and for the same reason: six digits in one
    run are read wrong. The grouping is display only -- what is copied is the
    digits.
    """
    if len(code) % 2 == 0:
        half = len(code) // 2
        return f"{code[:half]} {code[half:]}"
    return code


def otpauth_line(metadata: Mapping[str, str]) -> str | None:
    """The entry's otpauth URI, whichever key it arrived under.

    Searched by value rather than looked up by key. `pass-otp` writes the URI
    bare on its own line, which :func:`gtkpass.backends.metadata_pair` keys by
    its scheme, but an entry written by hand may well carry it as ``otp:`` or
    ``totp:`` instead, and all of them are the same line.
    """
    for value in metadata.values():
        if value.lower().startswith(OTPAUTH_PREFIX):
            return value
    return None


def _one(query: dict[str, list[str]], name: str) -> str:
    """The single value of a query parameter, or the empty string."""
    values = query.get(name) or []
    return values[0].strip() if values else ""


def _number(query: dict[str, list[str]], name: str, default: int) -> int:
    raw = _one(query, name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise OTPError(f"'{name}' is not a number: {raw!r}") from None


def _decode_secret(raw: str) -> bytes:
    """Decode the base32 secret, as forgivingly as the places it is copied from.

    Sites print the secret in spaced groups and people paste what they see;
    authenticators emit it without the ``=`` padding base64.b32decode insists
    on. Neither is a different secret, so neither is refused.
    """
    if not raw:
        raise OTPError("No secret in the otpauth:// URI")
    packed = raw.replace(" ", "").replace("-", "").upper()
    padded = packed + "=" * (-len(packed) % 8)
    try:
        secret = base64.b32decode(padded)
    except (binascii.Error, ValueError):
        raise OTPError("The secret is not valid base32") from None
    if not secret:
        raise OTPError("No secret in the otpauth:// URI")
    return secret


def _label(path: str) -> tuple[str, str]:
    """Split the URI's label into the issuer and the account it names.

    The label is ``issuer:account`` or a bare account, percent-encoded. A
    bare one is the account: it is what a person recognises, and calling it
    the issuer would put the wrong half in front of them.
    """
    label = unquote(path.lstrip("/")).strip()
    issuer, separator, account = label.partition(":")
    if not separator:
        return "", issuer.strip()
    return issuer.strip(), account.strip()
