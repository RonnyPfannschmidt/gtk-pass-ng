"""The edit dialog: what it shows, and what it hands back to be saved.

Entries are stored as free text -- the password on the first line, arbitrary
lines after it -- so the dialog splits on that boundary and joins it back. It
must not lose or reorder anything it did not touch, because whatever it hands
over replaces the entry wholesale.
"""

import pytest

from gtkpass._gi import Adw
from gtkpass.backends import PasswordEntry
from gtkpass.ui.password_edit import PasswordEditDialog

pytestmark = pytest.mark.gui

SECRET = "correct-horse-battery-staple"


@pytest.fixture(scope="session", autouse=True)
def adwaita():
    """Initialise libadwaita once; widget construction needs it."""
    Adw.init()


def entry(content: str) -> PasswordEntry:
    from pathlib import Path

    return PasswordEntry(
        name="email/work", path=Path("/store/email/work.gpg"), content=content
    )


@pytest.fixture
def dialog():
    return PasswordEditDialog()


def details(dialog) -> str:
    buffer = dialog.details_view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


def set_details(dialog, text: str) -> None:
    dialog.details_view.get_buffer().set_text(text)


class TestPrefill:
    def test_the_entry_name_is_shown(self, dialog):
        dialog.load(entry(f"{SECRET}\n"))

        assert dialog.name_row.get_subtitle() == "email/work"

    def test_the_password_is_the_first_line(self, dialog):
        dialog.load(entry(f"{SECRET}\nusername: alice\n"))

        assert dialog.password_row.get_text() == SECRET

    def test_the_remaining_lines_become_the_details(self, dialog):
        dialog.load(entry(f"{SECRET}\nhost: db.example.invalid\nport: 5432\n"))

        assert details(dialog) == "host: db.example.invalid\nport: 5432\n"

    def test_an_entry_with_no_details_leaves_them_empty(self, dialog):
        dialog.load(entry(f"{SECRET}\n"))

        assert details(dialog) == ""

    def test_an_entry_that_never_loaded_shows_nothing(self, dialog):
        dialog.load(entry(""))

        assert dialog.password_row.get_text() == ""
        assert details(dialog) == ""


class TestAssembly:
    def test_an_untouched_entry_round_trips(self, dialog):
        original = f"{SECRET}\nusername: alice\nurl: example.invalid\n"
        dialog.load(entry(original))

        assert dialog.content == original

    def test_a_new_password_replaces_only_the_first_line(self, dialog):
        dialog.load(entry(f"{SECRET}\nusername: alice\n"))

        dialog.password_row.set_text("replaced")

        assert dialog.content == "replaced\nusername: alice\n"

    def test_new_details_replace_everything_after_it(self, dialog):
        dialog.load(entry(f"{SECRET}\nhost: one\n"))

        set_details(dialog, "host: two\n")

        assert dialog.content == f"{SECRET}\nhost: two\n"

    def test_an_entry_without_a_trailing_newline_gains_one(self, dialog):
        """Stores conventionally end an entry with a newline; normalise to it."""
        dialog.load(entry(SECRET))

        assert dialog.content == f"{SECRET}\n"


class TestSaving:
    def saved_content(self, dialog):
        seen = []
        dialog.connect("saved", lambda _dialog, content: seen.append(content))
        return seen

    def test_saving_hands_over_the_edited_content(self, dialog):
        dialog.load(entry(f"{SECRET}\nusername: alice\n"))
        seen = self.saved_content(dialog)

        dialog.password_row.set_text("replaced")
        dialog.save_button.emit("clicked")

        assert seen == ["replaced\nusername: alice\n"]

    def test_cancelling_hands_over_nothing(self, dialog):
        dialog.load(entry(f"{SECRET}\n"))
        seen = self.saved_content(dialog)

        dialog.cancel_button.emit("clicked")

        assert seen == []

    def test_an_empty_password_cannot_be_saved(self, dialog):
        """An empty first line would leave an entry with no password at all."""
        dialog.load(entry(f"{SECRET}\n"))
        seen = self.saved_content(dialog)

        dialog.password_row.set_text("")
        dialog.save_button.emit("clicked")

        assert seen == []


class TestGeneratingAReplacement:
    """The generator was in the add dialog only, which is the wrong half.

    Adding an entry is the one time a password is *not* being replaced. Every
    rotation goes through here, and it went through here with nothing but an
    empty field to type into -- so the strongest thing the application can make
    was unavailable at exactly the moment it was wanted.
    """

    def test_the_generator_is_offered(self, dialog):
        dialog.load(entry(f"{SECRET}\n"))

        assert dialog.generator.get_visible()

    def test_generating_replaces_the_password(self, dialog):
        dialog.load(entry(f"{SECRET}\nusername: alice\n"))

        dialog.generator.generate_button.emit("clicked")

        assert dialog.password_row.get_text() != SECRET
        assert dialog.password_row.get_text()

    def test_generating_leaves_everything_below_it_alone(self, dialog):
        """The whole point of rotating rather than deleting and re-adding."""
        dialog.load(entry(f"{SECRET}\nusername: alice\nurl: example.invalid\n"))

        dialog.generator.generate_button.emit("clicked")

        below = dialog.content.partition("\n")[2]
        assert below == "username: alice\nurl: example.invalid\n"

    def test_the_scheme_on_offer_is_the_one_used(self, dialog):
        from gtkpass.utils.generate import Scheme

        dialog.load(entry(f"{SECRET}\n"))
        dialog.generator.scheme_row.set_selected(
            dialog.generator.SCHEMES.index(Scheme.DIGITS)
        )

        dialog.generator.generate_button.emit("clicked")

        assert dialog.password_row.get_text().isdigit()

    def test_a_generated_password_is_shown_rather_than_dotted_out(self, dialog):
        """Somebody who has just generated one has not seen it yet."""
        dialog.load(entry(f"{SECRET}\n"))

        dialog.generator.generate_button.emit("clicked")

        assert dialog.password_row.get_delegate().get_visibility() is True

    def test_it_is_the_generated_value_that_gets_saved(self, dialog):
        dialog.load(entry(f"{SECRET}\nusername: alice\n"))
        seen: list[str] = []
        dialog.connect("saved", lambda _dialog, content: seen.append(content))

        dialog.generator.generate_button.emit("clicked")
        generated = dialog.password_row.get_text()
        dialog.save_button.emit("clicked")

        assert seen == [f"{generated}\nusername: alice\n"]


class TestTheFieldsThePaneKnows:
    """Username and URL have rows of their own, as they do in the pane.

    The pane knew what ``username:`` and ``url:`` meant, and the dialogs made
    you type the key names by hand into a free-text box. The rows take those
    two out of the text on the way in and put them back on the way out --
    where they were, spelled as they were -- so that nothing else the entry
    carries is disturbed.
    """

    def test_the_username_is_pulled_into_its_row(self, dialog):
        dialog.load(entry(f"{SECRET}\nusername: alice\n"))

        assert dialog.username_row.get_text() == "alice"

    def test_the_url_is_pulled_into_its_row(self, dialog):
        dialog.load(entry(f"{SECRET}\nurl: https://example.invalid\n"))

        assert dialog.url_row.get_text() == "https://example.invalid"

    @pytest.mark.parametrize("key", ["user", "login"])
    def test_the_other_spellings_of_username_are_recognised(self, dialog, key):
        dialog.load(entry(f"{SECRET}\n{key}: alice\n"))

        assert dialog.username_row.get_text() == "alice"

    def test_the_pulled_lines_leave_the_details(self, dialog):
        dialog.load(
            entry(f"{SECRET}\nusername: alice\nhost: h\nurl: https://x.invalid\n")
        )

        assert details(dialog) == "host: h\n"

    def test_an_entry_without_them_leaves_the_rows_empty(self, dialog):
        dialog.load(entry(f"{SECRET}\nhost: h\n"))

        assert dialog.username_row.get_text() == ""
        assert dialog.url_row.get_text() == ""

    def test_a_changed_username_keeps_the_key_it_was_written_with(self, dialog):
        """A store written by another tool stays readable by that tool."""
        dialog.load(entry(f"{SECRET}\nuser: alice\n"))

        dialog.username_row.set_text("bob")

        assert dialog.content == f"{SECRET}\nuser: bob\n"

    def test_a_changed_line_keeps_its_place(self, dialog):
        dialog.load(entry(f"{SECRET}\nhost: h\nusername: alice\nsome notes\n"))

        dialog.username_row.set_text("bob")

        assert dialog.content == f"{SECRET}\nhost: h\nusername: bob\nsome notes\n"

    def test_an_emptied_username_drops_the_line(self, dialog):
        dialog.load(entry(f"{SECRET}\nusername: alice\nhost: h\n"))

        dialog.username_row.set_text("")

        assert dialog.content == f"{SECRET}\nhost: h\n"

    def test_a_username_given_to_an_entry_without_one_is_written_first(self, dialog):
        dialog.load(entry(f"{SECRET}\nhost: h\n"))

        dialog.username_row.set_text("alice")
        dialog.url_row.set_text("https://x.invalid")

        assert (
            dialog.content
            == f"{SECRET}\nusername: alice\nurl: https://x.invalid\nhost: h\n"
        )

    def test_an_untouched_line_is_written_back_exactly(self, dialog):
        """Odd spacing and all: a line nobody edited is not ours to tidy."""
        original = f"{SECRET}\nUsername:   alice  \n"
        dialog.load(entry(original))

        assert dialog.content == original

    def test_only_the_first_of_two_username_lines_is_taken(self, dialog):
        dialog.load(entry(f"{SECRET}\nusername: alice\nlogin: alice@x\n"))

        assert dialog.username_row.get_text() == "alice"
        assert details(dialog) == "login: alice@x\n"
