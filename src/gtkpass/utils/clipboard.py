"""Copying secrets to the clipboard, and taking them back out again.

Clearing is best effort. A clipboard manager may already have taken a copy, and
under Wayland a compositor may refuse a clear from an unfocused application.
Treat the timeout as damage limitation, not as a guarantee.

The timeout in particular protects against the wrong thing on its own. A
clipboard manager takes its copy the moment the selection changes, so by the
time the timer fires the password is already in a history that outlives both the
timer and the application. Nothing this side of the clipboard can reach into
that history; the only thing that keeps a secret out of it is asking not to be
recorded, which is what the hint below does.
"""

import logging

from gtkpass._gi import Gdk, GLib, GObject, Gtk

logger = logging.getLogger(__name__)

#: Offered alongside the text to mean "do not keep a copy of this".
#:
#: There is no specification for it. This spelling is Klipper's, and it is what
#: KeePassXC, Bitwarden and the other password managers offer, which makes it
#: the convention by use rather than by agreement. A clipboard manager that does
#: not know the type is no worse off than before: the text is offered next to
#: it, and that is what pasting reads.
PASSWORD_MANAGER_HINT = "x-kde-passwordManagerHint"

#: The hint's value. Its presence is what is read, but managers compare it.
SECRET_HINT = b"secret"


class ClipboardCopier:
    """Copies text and clears it again after a delay.

    One instance owns at most one pending clear, so repeated copies cannot
    leave an older timer behind to wipe a newer value early.
    """

    def __init__(self, widget: Gtk.Widget):
        # Resolve the display from the widget rather than taking the default
        # one, so this stays correct on a multi-display setup.
        self._widget = widget
        self._timeout_id: int | None = None
        self._pending: str | None = None

    def copy(self, text: str, timeout_seconds: int, secret: bool = True) -> None:
        """Put text on the clipboard, clearing it after ``timeout_seconds``.

        A timeout of zero disables clearing.

        ``secret`` decides whether clipboard managers are asked not to keep it.
        Not everything copied from a password manager is a password -- the sync
        dialog offers a shell command to run -- and marking those would take
        them out of the history the user wants them in.
        """
        if not text:
            return

        clipboard = self._clipboard()
        if clipboard is None:
            logger.warning("No display; cannot copy to the clipboard")
            return

        clipboard.set_content(self._content_for(text, secret))

        self.cancel_pending_clear()
        if timeout_seconds > 0:
            self._pending = text
            self._timeout_id = GLib.timeout_add_seconds(
                timeout_seconds, self._clear_if_unchanged
            )

    @staticmethod
    def _content_for(text: str, secret: bool) -> Gdk.ContentProvider:
        """What to offer the clipboard, and under which types.

        Gdk.Clipboard.set() is a varargs C function whose Python override is not
        available in every PyGObject build; set_content always is.
        """
        # The text comes first, so a paste that takes the first format it
        # recognises gets what the user meant to paste.
        text_provider = Gdk.ContentProvider.new_for_value(GObject.Value(str, text))
        if not secret:
            return text_provider
        return Gdk.ContentProvider.new_union(
            [
                text_provider,
                Gdk.ContentProvider.new_for_bytes(
                    PASSWORD_MANAGER_HINT, GLib.Bytes.new(SECRET_HINT)
                ),
            ]
        )

    def cancel_pending_clear(self) -> None:
        """Drop a scheduled clear without performing it."""
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None
        self._pending = None

    def clear_if_ours(self) -> None:
        """Take the copy back now rather than at the end of the timeout.

        For when the reason to keep it has gone -- the entry it came from is no
        longer the one on display. Same read-back check as the timeout, so
        clearing early cannot throw away something copied from somewhere else in
        the meantime.
        """
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None
        self._clear_if_unchanged()

    def clear_at_shutdown(self) -> None:
        """Empty the clipboard on the way out, without the read-back check.

        That check is asynchronous, and a window being destroyed has no main
        loop left to deliver the answer to. So this is the one clear that
        happens without knowing whether the value is still the one we put there
        -- bounded by there being a clear outstanding at all, which means a
        secret was copied within the timeout and has not been taken back.

        On Wayland the offer usually dies with the process anyway. This is for
        the sessions where it does not.
        """
        if self._pending is None:
            return
        self.cancel_pending_clear()
        clipboard = self._clipboard()
        if clipboard is not None:
            clipboard.set_content(None)
            logger.debug("Cleared the clipboard on the way out")

    def _clipboard(self) -> Gdk.Clipboard | None:
        display = self._widget.get_display()
        return display.get_clipboard() if display is not None else None

    def _clear_if_unchanged(self) -> bool:
        """Clear only what we put there.

        Blindly emptying the clipboard would throw away whatever the user
        copied from somewhere else in the meantime.
        """
        self._timeout_id = None
        clipboard = self._clipboard()
        if clipboard is None or self._pending is None:
            return GLib.SOURCE_REMOVE

        expected = self._pending
        self._pending = None

        def compare(_clipboard, result):
            try:
                current = clipboard.read_text_finish(result)
            except GLib.Error as error:
                logger.debug("Could not read the clipboard back: %s", error)
                return
            if current == expected:
                clipboard.set_content(None)
                logger.debug("Cleared the clipboard")

        clipboard.read_text_async(None, compare)
        return GLib.SOURCE_REMOVE
