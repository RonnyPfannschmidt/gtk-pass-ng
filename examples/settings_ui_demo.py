#!/usr/bin/env python3
"""Quick test script for settings UI."""

import sys

from gtkpass._gi import Adw
from gtkpass.ui.settings import SettingsWindow


class SettingsTestApp(Adw.Application):
    """Test application for settings window."""

    def __init__(self):
        super().__init__(application_id="org.ronny_pfannschmidt.gtkpass.SettingsTest")

    def do_activate(self):
        """Show settings window."""
        win = SettingsWindow(application=self)
        win.present()


if __name__ == "__main__":
    app = SettingsTestApp()
    sys.exit(app.run(sys.argv))
