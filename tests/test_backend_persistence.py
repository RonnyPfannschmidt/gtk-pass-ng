"""Settings UI and backend configuration persistence.

Demo backend behaviour used to live here; it is now part of the shared
conformance suite in ``test_backend_contract.py``, which runs it against every
registered backend rather than one hand-picked implementation.
"""

import pytest

from gtkpass._gi import Adw

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module", autouse=True)
def adwaita():
    Adw.init()


class TestSettingsWindow:
    def test_can_be_created(self):
        from gtkpass.ui.settings import SettingsWindow

        window = SettingsWindow()

        assert window.backends_group is not None
        assert window.backend_combo is not None


class TestRenamingThroughTheDialog:
    """Typing a new name into the dialog must reach GSettings.

    The entry existed for a while with nothing wired behind it: get_display_name
    was never called and the save path never wrote the name anywhere.
    """

    BACKEND_ID = "demo_1766234611"

    @pytest.fixture
    def dialog(self):
        from gtkpass._gi import GLib
        from gtkpass.config import get_settings, set_backend_display_name
        from gtkpass.ui.settings import SettingsWindow

        settings = get_settings()
        previous = settings.get_value("backend-instances")
        settings.set_value(
            "backend-instances", GLib.Variant("a(ss)", [(self.BACKEND_ID, "demo")])
        )
        yield SettingsWindow()
        set_backend_display_name("demo", self.BACKEND_ID, "")
        settings.set_value("backend-instances", previous)

    def test_typing_a_name_persists_it(self, dialog):
        from gtkpass.config import get_backend_display_name

        row = dialog.backend_rows[self.BACKEND_ID]
        row.name_entry.set_text("Team Vault")

        assert get_backend_display_name("demo", self.BACKEND_ID) == "Team Vault"

    def test_the_entry_is_prefilled_from_storage(self, dialog):
        from gtkpass.config import set_backend_display_name
        from gtkpass.ui.settings import SettingsWindow

        set_backend_display_name("demo", self.BACKEND_ID, "Preexisting")

        reopened = SettingsWindow()

        assert (
            reopened.backend_rows[self.BACKEND_ID].name_entry.get_text()
            == "Preexisting"
        )
