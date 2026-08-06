"""The detail pane: how a decrypted entry is mapped onto rows."""

from pathlib import Path

import pytest

from gtkpass._gi import Adw
from gtkpass.backends import PasswordEntry
from gtkpass.ui.password_detail import PLACEHOLDER, PasswordDetailView

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module", autouse=True)
def adwaita():
    Adw.init()


def entry(content: str, name: str = "example") -> PasswordEntry:
    return PasswordEntry(name=name, path=Path(f"/tmp/{name}.gpg"), content=content)


@pytest.fixture
def view():
    return PasswordDetailView()


class TestFieldMapping:
    def test_password_is_the_first_line(self, view):
        view.show_entry(entry("s3cret\nusername: alice"))

        assert view.password_row.get_text() == "s3cret"

    def test_name_is_shown(self, view):
        view.show_entry(entry("s3cret", name="email/work"))

        assert view.name_row.get_subtitle() == "email/work"

    @pytest.mark.parametrize("key", ["username", "user", "login"])
    def test_username_accepts_the_usual_spellings(self, view, key):
        """Stores written by different tools disagree on the key."""
        view.show_entry(entry(f"s3cret\n{key}: alice"))

        assert view.username_row.get_subtitle() == "alice"

    @pytest.mark.parametrize("key", ["url", "website", "uri"])
    def test_url_accepts_the_usual_spellings(self, view, key):
        view.show_entry(entry(f"s3cret\n{key}: https://example.com"))

        assert view.url_row.get_subtitle() == "https://example.com"

    def test_absent_fields_show_a_placeholder(self, view):
        view.show_entry(entry("s3cret"))

        assert view.username_row.get_subtitle() == PLACEHOLDER
        assert view.url_row.get_subtitle() == PLACEHOLDER


class TestNotes:
    def test_a_notes_key_is_shown(self, view):
        """This is how the demo data and pass templates write notes."""
        view.show_entry(entry("s3cret\nnotes: Primary account"))

        assert view.notes_label.get_text() == "Primary account"
        assert view.notes_group.get_visible()

    def test_free_text_lines_are_shown(self, view):
        view.show_entry(entry("s3cret\nusername: alice\nrecovery codes in the safe"))

        assert view.notes_label.get_text() == "recovery codes in the safe"

    def test_the_group_is_hidden_without_notes(self, view):
        view.show_entry(entry("s3cret\nusername: alice"))

        assert not view.notes_group.get_visible()


class TestStackState:
    def test_loading_shows_the_spinner_page(self, view):
        view.show_loading("email/work")

        assert view.stack.get_visible_child_name() == "loading"
        assert view.spinner.get_spinning()

    def test_showing_an_entry_stops_the_spinner(self, view):
        view.show_loading()

        view.show_entry(entry("s3cret"))

        assert view.stack.get_visible_child_name() == "content"
        assert not view.spinner.get_spinning()


class TestSecrets:
    def test_the_previous_entry_is_scrubbed(self, view):
        """Plaintext must not be kept alive once another entry is shown."""
        first = entry("s3cret", name="first")
        view.show_entry(first)

        view.show_entry(entry("other", name="second"))

        assert first.content is None

    def test_clear_scrubs_and_blanks(self, view):
        current = entry("s3cret")
        view.show_entry(current)

        view.clear()

        assert current.content is None
        assert view.password_row.get_text() == ""


class TestCopyRequests:
    """The view asks for a copy; the window owns the clipboard and timeout."""

    def emitted(self, view, button):
        captured = []
        view.connect("copy-requested", lambda _v, field, value: captured.append(
            (field, value)
        ))
        button.emit("clicked")
        return captured

    def test_copying_the_password(self, view):
        view.show_entry(entry("s3cret\nusername: alice"))

        assert self.emitted(view, view.copy_password_btn) == [("Password", "s3cret")]

    def test_copying_the_username(self, view):
        view.show_entry(entry("s3cret\nusername: alice"))

        assert self.emitted(view, view.copy_username_btn) == [("Username", "alice")]

    def test_copying_the_url(self, view):
        view.show_entry(entry("s3cret\nurl: https://example.com"))

        assert self.emitted(view, view.copy_url_btn) == [
            ("URL", "https://example.com")
        ]

    def test_an_empty_field_asks_for_nothing(self, view):
        """The placeholder dash must never reach the clipboard."""
        view.show_entry(entry("s3cret"))

        assert self.emitted(view, view.copy_username_btn) == []
