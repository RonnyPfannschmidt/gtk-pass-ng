"""Generating a password.

`secrets` rather than `random`: the latter is seeded from the clock and its
state is recoverable from its output, which for a password generator is the
whole of the matter. There is no dependency here and no configuration -- the
one decision worth offering is whether symbols are allowed, because some sites
still refuse them, and a refused password is a retype at the worst moment.
"""

import secrets
import string

#: Characters a generated password is drawn from.
#:
#: O and 0, and l, I and 1, are left out on purpose. A generated password gets
#: read off one screen and typed into another, often on a phone, and those two
#: pairs are what cost somebody three attempts before it occurs to them to try
#: the other character.
_AMBIGUOUS = "O0lI1"

LETTERS_AND_DIGITS = "".join(
    character
    for character in string.ascii_letters + string.digits
    if character not in _AMBIGUOUS
)

#: The symbols, kept to ones that survive a shell, a URL and a form field.
SYMBOLS = "!@#$%^&*-_=+?"

ALPHABET = LETTERS_AND_DIGITS + SYMBOLS

#: Long enough that the alphabet above carries well over 100 bits.
DEFAULT_LENGTH = 20


def generate_password(length: int = DEFAULT_LENGTH, symbols: bool = True) -> str:
    """A password of ``length`` characters drawn uniformly from the alphabet.

    Args:
        length: How many characters. Must be at least one.
        symbols: Whether punctuation may appear.

    Raises:
        ValueError: If ``length`` is not positive, rather than handing back
            something unusable.
    """
    if length < 1:
        raise ValueError("A password needs at least one character")

    alphabet = ALPHABET if symbols else LETTERS_AND_DIGITS
    return "".join(secrets.choice(alphabet) for _ in range(length))
