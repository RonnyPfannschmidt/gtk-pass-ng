"""Generating a password.

Short enough to be obviously right, and the one place it matters that it is:
this is `secrets` and nothing else, because a generator seeded from the clock
or drawn from `random` produces passwords somebody can reproduce.
"""

import pytest

from gtkpass.utils.generate import ALPHABET, DEFAULT_LENGTH, generate_password


class TestLength:
    def test_the_default_is_long_enough_to_be_worth_generating(self):
        assert len(generate_password()) == DEFAULT_LENGTH
        assert DEFAULT_LENGTH >= 16

    def test_a_length_is_honoured(self):
        assert len(generate_password(length=32)) == 32

    def test_a_useless_length_is_refused(self):
        """Rather than quietly handing back something unusable."""
        with pytest.raises(ValueError):
            generate_password(length=0)


class TestAlphabet:
    def test_only_the_declared_characters_are_used(self):
        assert set(generate_password(length=200)) <= set(ALPHABET)

    def test_symbols_can_be_left_out(self):
        """Some sites still refuse them, and a refused password is a retype."""
        generated = generate_password(length=200, symbols=False)

        assert generated.isalnum()

    def test_ambiguous_characters_are_left_out(self):
        """A generated password gets read off a screen and typed on a phone.

        O and 0, l and 1 and I are the pairs that cost somebody three attempts
        before they think to try the other one.
        """
        assert not set("O0lI1") & set(ALPHABET)


class TestUnpredictability:
    def test_two_passwords_differ(self):
        assert generate_password() != generate_password()

    def test_it_draws_from_secrets(self, monkeypatch):
        """The module has to be the audited one, whatever it is called here.

        `random` is seeded from the clock and its state can be recovered from
        its output, which for a password generator is the whole ballgame.
        """
        import gtkpass.utils.generate as module

        calls = []

        def record(sequence):
            calls.append(sequence)
            return sequence[0]

        monkeypatch.setattr(module.secrets, "choice", record)

        generate_password(length=5)

        assert len(calls) == 5
