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

    def test_an_applied_name_persists(self, dialog):
        from gtkpass.config import get_backend_display_name

        row = dialog.backend_rows[self.BACKEND_ID]
        row.name_row.set_text("Team Vault")
        row.name_row.emit("apply")

        assert get_backend_display_name("demo", self.BACKEND_ID) == "Team Vault"

    def test_a_name_still_being_typed_is_not_saved_yet(self, dialog):
        """Every keystroke used to be a save, and every save a reload.

        The window answers a settings change by shutting its thread pool down
        and building every backend again -- git over the store, a D-Bus
        connection, possibly a keyring prompt -- so typing a twelve-letter name
        was twelve of those. The row saves when the name is applied, with
        Enter or the row's own button, and not before.
        """
        from gtkpass.config import get_backend_display_name

        row = dialog.backend_rows[self.BACKEND_ID]
        row.name_row.set_text("Team Vault")

        assert get_backend_display_name("demo", self.BACKEND_ID) != "Team Vault"

    def test_the_entry_is_prefilled_from_storage(self, dialog):
        from gtkpass.config import set_backend_display_name
        from gtkpass.ui.settings import SettingsWindow

        set_backend_display_name("demo", self.BACKEND_ID, "Preexisting")

        reopened = SettingsWindow()

        assert (
            reopened.backend_rows[self.BACKEND_ID].name_row.get_text() == "Preexisting"
        )


class TestChoosingAPath:
    """A store directory was typed in and nothing else.

    Under Flatpak that is worse than inconvenient: choosing through the file
    chooser goes through the portal, and the portal is what grants the sandbox
    access to the directory. A path typed by hand is a store the application
    then cannot open, and it says so later and in terms of GPG.
    """

    @pytest.fixture
    def row(self):
        from gtkpass.ui.settings import BackendSettingsRow

        return BackendSettingsRow("pass", "pass_1")

    def test_every_path_row_has_a_chooser(self, row):
        from gtkpass.ui.settings import BackendSettingsRow

        rows = {
            "demo": ("demo_path_row", "demo_path_button"),
            "pass": ("pass_store_row", "pass_store_button"),
            "direct": ("direct_store_row", "direct_store_button"),
        }
        for backend_type, (row_name, button_name) in rows.items():
            built = BackendSettingsRow(backend_type, f"{backend_type}_1")
            chooser = built._chooser_for(getattr(built, button_name))
            assert chooser is not None
            assert chooser[0] is getattr(built, row_name)

    def test_a_store_asks_for_a_folder(self, row):
        assert row._chooser_for(row.pass_store_button) == (row.pass_store_row, True)

    def test_the_demo_data_asks_for_a_file(self):
        from gtkpass.ui.settings import BackendSettingsRow

        built = BackendSettingsRow("demo", "demo_1")

        assert built._chooser_for(built.demo_path_button) == (
            built.demo_path_row,
            False,
        )

    def test_a_chosen_path_lands_in_its_row(self, row):
        from gtkpass._gi import Gio

        row.apply_choice(row.pass_store_row, Gio.File.new_for_path("/srv/store"))

        assert row.pass_store_row.get_text() == "/srv/store"

    def test_a_chosen_path_is_read_back_as_a_setting(self, row):
        """Setting the text is what saves it, exactly as typing would."""
        from gtkpass._gi import Gio

        row.apply_choice(row.pass_store_row, Gio.File.new_for_path("/srv/store"))

        assert str(row.get_settings().password_store_dir) == "/srv/store"

    def test_a_cancelled_chooser_leaves_the_row_alone(self, row):
        row.pass_store_row.set_text("/srv/store")

        row.apply_choice(row.pass_store_row, None)

        assert row.pass_store_row.get_text() == "/srv/store"


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

        dialog._remove_backend(row)

        assert dialog.backend_rows == {}
        assert list(get_settings().get_value("backend-instances")) == []


class TestRemovingAsks:
    """It used to go the moment the button was pressed.

    The row, the name somebody had typed and the store directory they had
    chosen were all thrown away with no question and no way back -- and under
    Flatpak, so was the access that choosing the directory had granted.
    """

    @pytest.fixture
    def configured(self):
        from gtkpass._gi import GLib
        from gtkpass.config import get_settings
        from gtkpass.ui.settings import SettingsWindow

        settings = get_settings()
        previous = settings.get_value("backend-instances")
        settings.set_value("backend-instances", GLib.Variant("a(ss)", []))
        dialog = SettingsWindow()
        dialog.backend_combo.set_selected(0)
        dialog._on_add_backend(None)
        yield dialog, next(iter(dialog.backend_rows.values()))
        settings.set_value("backend-instances", previous)

    def test_the_button_asks_rather_than_removing(self, configured):
        dialog, row = configured

        row.remove_button.emit("clicked")

        assert dialog.backend_rows, "the backend was removed without asking"

    def test_the_question_says_the_store_is_left_alone(self, configured):
        dialog, row = configured

        question = dialog._on_remove_backend(row)

        assert "Nothing in the store itself" in question.get_body()

    def test_cancelling_keeps_it(self, configured):
        dialog, row = configured

        dialog._on_remove_backend(row).emit("response", "cancel")

        assert row.backend_id in dialog.backend_rows

    def test_confirming_removes_it(self, configured):
        dialog, row = configured

        dialog._on_remove_backend(row).emit("response", "remove")

        assert dialog.backend_rows == {}


class Counting:
    """A settings object that counts what is written to it."""

    def __init__(self, settings):
        self._settings = settings
        self.writes = 0

    def __getattr__(self, name):
        attribute = getattr(self._settings, name)
        if name.startswith("set_"):

            def counted(*args):
                self.writes += 1
                return attribute(*args)

            return counted
        return attribute


class TestSavingWritesOnlyWhatChanged:
    """A write of an unchanged value is still a write, and the window hears it.

    The keyfile backend, which the development launcher uses, emits ``changed``
    for every write whether or not the value differs; the memory backend the
    tests run on does not, which is how this went unnoticed. Each emission
    costs the window a full rebuild of every backend, so an unchanged value
    must not be written at all.
    """

    BACKEND_ID = "demo_1766234612"

    @pytest.fixture
    def dialog(self, monkeypatch):
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

    def test_an_unchanged_instance_list_is_not_rewritten(self, dialog, monkeypatch):
        counted = Counting(dialog.settings)
        monkeypatch.setattr(dialog, "settings", counted)

        dialog._save_backend_configs()

        assert counted.writes == 0

    def test_an_unchanged_backend_setting_is_not_rewritten(self, dialog, monkeypatch):
        import gtkpass.config
        import gtkpass.ui.settings

        handed_out: list[Counting] = []

        def counting(backend_type, backend_id):
            counted = Counting(real(backend_type, backend_id))
            handed_out.append(counted)
            return counted

        real = gtkpass.config.get_backend_settings
        monkeypatch.setattr(gtkpass.ui.settings, "get_backend_settings", counting)
        monkeypatch.setattr(gtkpass.config, "get_backend_settings", counting)

        dialog._save_backend_configs()

        assert sum(counted.writes for counted in handed_out) == 0

    def test_a_changed_setting_is_still_written(self, dialog):
        from gtkpass.config import get_backend_settings

        row = dialog.backend_rows[self.BACKEND_ID]
        row.demo_path_row.set_text("/srv/demo.json")
        row.demo_path_row.emit("apply")

        stored = get_backend_settings("demo", self.BACKEND_ID)
        try:
            assert stored.get_string("custom-data-path") == "/srv/demo.json"
        finally:
            stored.reset("custom-data-path")
