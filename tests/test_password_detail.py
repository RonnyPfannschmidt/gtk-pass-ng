"""The detail pane: how a decrypted entry is mapped onto rows."""

import time
from pathlib import Path

import pytest

from gtkpass._gi import Adw, GLib, Gtk
from gtkpass.backends import PasswordEntry
from gtkpass.ui.password_detail import PLACEHOLDER, PasswordDetailView

pytestmark = pytest.mark.gui


def labels_of(widget):
    """Text of every Label below ``widget``."""

    def walk(parent):
        child = parent.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Label):
                yield child.get_text()
            yield from walk(child)
            child = child.get_next_sibling()

    return set(walk(widget))


def present_until(view, ready):
    """Show the pane until ``ready(view)`` holds, and report what it rendered.

    Rows are built during a layout pass, so nothing is on screen until the loop
    turns. Waiting on the condition rather than a fixed delay is what keeps
    this from failing on a loaded machine.
    """
    window = Gtk.Window(child=view, default_width=400, default_height=400)
    window.present()

    context = GLib.MainContext.default()
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not ready(view):
        context.iteration(may_block=False)
        time.sleep(0.005)
    return labels_of(view.extras_view)


@pytest.fixture(scope="module", autouse=True)
def adwaita():
    Adw.init()


def entry(content: str, name: str = "example") -> PasswordEntry:
    return PasswordEntry(name=name, path=Path(f"/tmp/{name}.gpg"), content=content)


@pytest.fixture
def view():
    return PasswordDetailView()


class TestHeading:
    """The entry names the pane; it is not one of the pane's fields.

    A row labelled "Name" whose value was the entry itself said nothing the
    heading does not, and pushed the fields that matter further down.
    """

    def test_the_entry_is_the_title(self, view):
        view.show_entry(entry("s3cret", name="email/work"))

        assert view.title_label.get_text() == "work"

    def test_the_folder_leads_into_it(self, view):
        """The two labels sit on one line, so they read as one path."""
        view.show_entry(entry("s3cret", name="email/work"))

        assert view.path_label.get_text() == "email/"
        assert view.path_label.get_visible()

    def test_a_nested_folder_keeps_its_whole_path(self, view):
        view.show_entry(entry("s3cret", name="web/news/hn"))

        assert view.title_label.get_text() == "hn"
        assert view.path_label.get_text() == "web/news/"

    def test_a_top_level_entry_has_no_folder_line(self, view):
        view.show_entry(entry("s3cret", name="wifi"))

        assert view.title_label.get_text() == "wifi"
        assert not view.path_label.get_visible()

    def test_clear_blanks_the_heading(self, view):
        view.show_entry(entry("s3cret", name="email/work"))

        view.clear()

        assert view.title_label.get_text() == ""
        assert not view.path_label.get_visible()


class TestFieldMapping:
    def test_password_is_the_first_line(self, view):
        view.show_entry(entry("s3cret\nusername: alice"))

        assert view.password_row.get_text() == "s3cret"

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


class TestOtherFields:
    """Anything the pane has no dedicated row for still has to be shown.

    Stores carry whatever their owner put there -- ``host``, ``port``,
    ``account``, ``server`` -- and every one of those used to be dropped on the
    floor: not a row, and not part of the notes either, because a line with a
    colon in it is read as metadata rather than as prose.
    """

    def fields(self, view):
        model = view.extra_fields
        return [
            (model.get_item(index).key, model.get_item(index).value)
            for index in range(model.get_n_items())
        ]

    def test_an_unknown_field_is_shown(self, view):
        view.show_entry(entry("s3cret\nhost: db.example.com\nport: 5432"))

        assert self.fields(view) == [("host", "db.example.com"), ("port", "5432")]

    def test_fields_with_rows_of_their_own_are_not_repeated(self, view):
        view.show_entry(
            entry("s3cret\nusername: alice\nurl: https://example.com\nnotes: hello")
        )

        assert self.fields(view) == []

    def test_the_group_is_hidden_when_there_are_none(self, view):
        view.show_entry(entry("s3cret\nusername: alice"))

        assert not view.extras_group.get_visible()

    def test_the_group_appears_when_there_are_some(self, view):
        view.show_entry(entry("s3cret\naccount: 1234567890"))

        assert view.extras_group.get_visible()

    def test_moving_to_another_entry_drops_the_previous_fields(self, view):
        view.show_entry(entry("s3cret\nhost: db.example.com"))

        view.show_entry(entry("other\nport: 5432", name="second"))

        assert self.fields(view) == [("port", "5432")]

    def test_clear_empties_them(self, view):
        view.show_entry(entry("s3cret\nhost: db.example.com"))

        view.clear()

        assert self.fields(view) == []
        assert not view.extras_group.get_visible()

    def test_the_rows_reach_the_display(self, view):
        """The model being right proves nothing about the row template.

        These rows come from a BuilderListItemFactory, whose bindings only run
        when a row is built, so a broken one leaves every assertion above
        passing and the group on screen empty.
        """
        view.show_entry(entry("s3cret\nhost: db.example.com"))

        rendered = present_until(
            view, lambda v: {"host", "db.example.com"} <= labels_of(v.extras_view)
        )

        assert {"host", "db.example.com"} <= rendered


class TestFieldsThatAreThemselvesSecrets:
    """The first line is not the only secret an entry carries.

    An `otpauth://` line is a shared secret that generates every future code; a
    `pin` or a `recovery` field is a password by another name. All of them were
    rendered as plain labels the moment the entry was selected, while the
    password above them was dotted out -- so a shoulder, a screen share or a
    screenshot got the parts nobody thought to hide.
    """

    def displayed(self, view):
        model = view.extra_fields
        return {
            model.get_item(index).key: model.get_item(index).display
            for index in range(model.get_n_items())
        }

    def test_a_one_time_password_seed_is_masked(self, view):
        view.show_entry(entry("s3cret\notpauth: otpauth://totp/x?secret=ABCDEF"))

        assert "ABCDEF" not in self.displayed(view)["otpauth"]

    @pytest.mark.parametrize(
        "key", ["otp", "totp", "pin", "secret", "token", "recovery", "seed", "key"]
    )
    def test_the_keys_that_name_a_secret_are_masked(self, view, key):
        view.show_entry(entry(f"s3cret\n{key}: 123456"))

        assert self.displayed(view)[key] != "123456"

    def test_an_ordinary_field_is_left_alone(self, view):
        """Masking a hostname would be a worse interface for no benefit."""
        view.show_entry(entry("s3cret\nhost: db.example.com\nport: 5432"))

        assert self.displayed(view) == {"host": "db.example.com", "port": "5432"}

    def test_revealing_shows_them(self, view):
        view.show_entry(entry("s3cret\npin: 1234\nhost: db.example.com"))

        view.set_reveal_extras(True)

        assert self.displayed(view)["pin"] == "1234"

    def test_the_control_is_offered_only_when_something_is_hidden(self, view):
        view.show_entry(entry("s3cret\nhost: db.example.com"))
        assert not view.reveal_extras_button.get_visible()

        view.show_entry(entry("s3cret\npin: 1234", name="second"))

        assert view.reveal_extras_button.get_visible()

    def test_moving_to_another_entry_hides_them_again(self, view):
        view.show_entry(entry("s3cret\npin: 1234"))
        view.set_reveal_extras(True)

        view.show_entry(entry("other\npin: 9999", name="second"))

        assert self.displayed(view)["pin"] != "9999"

    def test_the_masking_reaches_the_display(self, view):
        """The row template binds a property; the model alone proves nothing."""
        view.show_entry(entry("s3cret\npin: 1234"))

        rendered = present_until(view, lambda v: "pin" in labels_of(v.extras_view))

        assert "1234" not in rendered

    def test_the_revealed_value_reaches_the_display(self, view):
        view.show_entry(entry("s3cret\npin: 1234"))
        view.set_reveal_extras(True)

        rendered = present_until(view, lambda v: "1234" in labels_of(v.extras_view))

        assert "1234" in rendered


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


class TestRevealingThePassword:
    """The 'show hidden passwords' preference, which never worked.

    It was bound to a 'show-password' property that Adw.PasswordEntryRow does
    not have, so every window construction logged a GLib-GIO-CRITICAL and the
    setting did nothing. The row's text visibility lives on its GtkEditable
    delegate instead.
    """

    def shown(self, view) -> bool:
        return view.password_row.get_delegate().get_visibility()

    def test_a_password_starts_hidden(self, view):
        view.show_entry(entry("s3cret"))

        assert not self.shown(view)

    def test_it_can_be_revealed(self, view):
        view.show_entry(entry("s3cret"))

        view.set_reveal_password(True)

        assert self.shown(view)

    def test_it_can_be_hidden_again(self, view):
        view.show_entry(entry("s3cret"))
        view.set_reveal_password(True)

        view.set_reveal_password(False)

        assert not self.shown(view)

    def test_revealing_survives_the_next_entry(self, view):
        """Arrow-keying to another entry must not silently re-hide it."""
        view.show_entry(entry("s3cret"))
        view.set_reveal_password(True)

        view.show_entry(entry("other", name="second"))

        assert self.shown(view)


class TestCopyRequests:
    """The view asks for a copy; the window owns the clipboard and timeout."""

    def emitted(self, view, button):
        captured = []
        view.connect(
            "copy-requested", lambda _v, field, value: captured.append((field, value))
        )
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

        assert self.emitted(view, view.copy_url_btn) == [("URL", "https://example.com")]

    def test_an_empty_field_asks_for_nothing(self, view):
        """The placeholder dash must never reach the clipboard."""
        view.show_entry(entry("s3cret"))

        assert self.emitted(view, view.copy_username_btn) == []
