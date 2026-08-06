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
