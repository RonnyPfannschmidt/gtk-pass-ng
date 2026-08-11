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
        row.name_row.set_text("Team Vault")

        assert get_backend_display_name("demo", self.BACKEND_ID) == "Team Vault"

    def test_the_entry_is_prefilled_from_storage(self, dialog):
        from gtkpass.config import set_backend_display_name
        from gtkpass.ui.settings import SettingsWindow

        set_backend_display_name("demo", self.BACKEND_ID, "Preexisting")

        reopened = SettingsWindow()

        assert (
            reopened.backend_rows[self.BACKEND_ID].name_row.get_text() == "Preexisting"
        )


class TestAddingAndRemoving:
    """The add flow reads the combo row's selection index, not a string id."""

    @pytest.fixture
    def dialog(self):
        from gtkpass._gi import GLib
        from gtkpass.config import get_settings
        from gtkpass.ui.settings import SettingsWindow

        settings = get_settings()
        previous = settings.get_value("backend-instances")
        settings.set_value("backend-instances", GLib.Variant("a(ss)", []))
        yield SettingsWindow()
        settings.set_value("backend-instances", previous)

    def test_the_combo_offers_every_backend_type(self, dialog):
        from gtkpass.ui.settings import BACKEND_TYPES

        assert dialog.backend_combo.get_model().get_n_items() == len(BACKEND_TYPES)

    def test_adding_uses_the_selected_type(self, dialog):
        from gtkpass.ui.settings import BACKEND_TYPES

        dialog.backend_combo.set_selected(BACKEND_TYPES.index("pass"))
        dialog._on_add_backend(None)

        (row,) = dialog.backend_rows.values()
        assert row.backend_type == "pass"
        assert row.pass_store_row.get_visible()
        assert not row.demo_path_row.get_visible()

    def test_added_backends_are_recorded(self, dialog):
        from gtkpass.config import get_settings

        dialog.backend_combo.set_selected(0)
        dialog._on_add_backend(None)

        recorded = list(get_settings().get_value("backend-instances"))
        assert [backend_type for _, backend_type in recorded] == ["demo"]

    def test_two_of_a_type_added_at_once_stay_apart(self, dialog):
        """The id used to be the type and the wall clock in whole seconds.

        Two backends of the same type added within the same second were handed
        the same id, so the second overwrote the first in the row dictionary
        and both read and wrote the same relocatable schema path -- one row on
        screen where two had been asked for, and one store's settings quietly
        holding the other's.
        """
        from gtkpass.config import get_settings

        dialog.backend_combo.set_selected(0)
        dialog._on_add_backend(None)
        dialog._on_add_backend(None)

        assert len(dialog.backend_rows) == 2
        recorded = [
            backend_id
            for backend_id, _ in get_settings().get_value("backend-instances")
        ]
        assert len(set(recorded)) == 2

    def test_an_id_is_not_reused_by_a_later_session(self, dialog):
        """A row already recorded holds its id against a new one."""
        from gtkpass.ui.settings import SettingsWindow

        dialog.backend_combo.set_selected(0)
        dialog._on_add_backend(None)
        (existing,) = list(dialog.backend_rows)

        reopened = SettingsWindow()
        reopened.backend_combo.set_selected(0)
        reopened._on_add_backend(None)

        assert existing in reopened.backend_rows
        assert len(reopened.backend_rows) == 2

    def test_removing_forgets_the_backend(self, dialog):
        from gtkpass.config import get_settings

        dialog.backend_combo.set_selected(0)
        dialog._on_add_backend(None)
        (row,) = list(dialog.backend_rows.values())

        dialog._on_remove_backend(row)

        assert dialog.backend_rows == {}
        assert list(get_settings().get_value("backend-instances")) == []
