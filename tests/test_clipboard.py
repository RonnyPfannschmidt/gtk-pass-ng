"""Copying a secret, and getting it back off the clipboard again.

The timeout was the only protection here, and it protects against the wrong
thing. A clipboard manager takes its copy the moment the selection changes, so
by the time the timer fires the password is already in a history that survives
it -- and survives the application. What keeps it out of that history is telling
the manager not to keep it, which is what the hint below is for.
"""

import time

import pytest

from gtkpass._gi import Gdk, GLib, GObject, Gtk
from gtkpass.utils.clipboard import PASSWORD_MANAGER_HINT, ClipboardCopier

pytestmark = pytest.mark.gui


def pump(seconds: float = 0.3) -> None:
    """Turn the main loop, so an asynchronous clipboard read can land."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        context.iteration(may_block=False)
        time.sleep(0.005)


@pytest.fixture
def copier():
    """A copier over a real display's clipboard."""
    window = Gtk.Window()
    copier = ClipboardCopier(window)
    if copier._clipboard() is None:
        pytest.skip("no display, so there is no clipboard to copy to")
    yield copier
    copier.cancel_pending_clear()
    window.destroy()


def clipboard_of(copier):
    clipboard = copier._clipboard()
    assert clipboard is not None
    return clipboard


class TestWhatIsOffered:
    def test_a_secret_is_marked_as_one(self, copier):
        """Klipper's spelling, and what KeePassXC and Bitwarden offer.

        There is no specification for it; this is a convention by use. A manager
        that does not know the type is unaffected, because the text is offered
        alongside it.
        """
        copier.copy("hunter2", 0)

        formats = clipboard_of(copier).get_formats()

        assert formats.contain_mime_type(PASSWORD_MANAGER_HINT)

    def test_the_text_is_still_what_gets_pasted(self, copier):
        copier.copy("hunter2", 0)

        formats = clipboard_of(copier).get_formats()

        assert formats.contain_gtype(GObject.TYPE_STRING)

    def test_something_that_is_not_a_secret_is_not_marked(self, copier):
        """The sync dialog copies a shell command, which belongs in history."""
        copier.copy("flatpak override --user", 0, secret=False)

        formats = clipboard_of(copier).get_formats()

        assert not formats.contain_mime_type(PASSWORD_MANAGER_HINT)
        assert formats.contain_gtype(GObject.TYPE_STRING)


class TestTakingItBack:
    def test_it_can_be_taken_back_before_the_timeout(self, copier):
        copier.copy("hunter2", 45)

        copier.clear_if_ours()
        pump()

        assert clipboard_of(copier).get_content() is None

    def test_it_leaves_alone_what_somebody_else_copied(self, copier):
        """The read-back check is what makes clearing safe to do eagerly."""
        copier.copy("hunter2", 45)
        clipboard_of(copier).set_content(
            Gdk.ContentProvider.new_for_value(
                GObject.Value(str, "something the user copied")
            )
        )

        copier.clear_if_ours()
        pump()

        assert clipboard_of(copier).get_content() is not None

    def test_shutting_down_empties_it(self, copier):
        copier.copy("hunter2", 45)

        copier.clear_at_shutdown()

        assert clipboard_of(copier).get_content() is None

    def test_shutting_down_with_nothing_outstanding_leaves_it_alone(self, copier):
        """Quitting must not wipe a clipboard this application never wrote."""
        copier.copy("hunter2", 0)  # no timeout, so nothing is outstanding

        copier.clear_at_shutdown()

        assert clipboard_of(copier).get_content() is not None
