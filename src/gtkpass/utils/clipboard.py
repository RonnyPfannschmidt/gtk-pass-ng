"""Copying secrets to the clipboard, and taking them back out again.

Clearing is best effort. A clipboard manager may already have taken a copy, and
under Wayland a compositor may refuse a clear from an unfocused application.
Treat the timeout as damage limitation, not as a guarantee.
"""

import logging

from gtkpass._gi import Gdk, GLib, GObject, Gtk

logger = logging.getLogger(__name__)


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

    def copy(self, text: str, timeout_seconds: int) -> None:
        """Put text on the clipboard, clearing it after ``timeout_seconds``.

        A timeout of zero disables clearing.
        """
        if not text:
            return

        clipboard = self._clipboard()
        if clipboard is None:
            logger.warning("No display; cannot copy to the clipboard")
            return

        # Gdk.Clipboard.set() is a varargs C function whose Python override is
        # not available in every PyGObject build; set_content always is.
        clipboard.set_content(
            Gdk.ContentProvider.new_for_value(GObject.Value(str, text))
        )

        self.cancel_pending_clear()
        if timeout_seconds > 0:
            self._pending = text
            self._timeout_id = GLib.timeout_add_seconds(
                timeout_seconds, self._clear_if_unchanged
            )

    def cancel_pending_clear(self) -> None:
        """Drop a scheduled clear without performing it."""
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None
        self._pending = None

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
