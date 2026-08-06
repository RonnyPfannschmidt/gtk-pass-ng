"""Tests for the application object."""

import pytest

pytestmark = pytest.mark.gui


class TestGTKPassApp:
    def test_can_be_constructed(self):
        """Constructing the app must not create a window yet."""
        from gtkpass.app import GTKPassApp

        app = GTKPassApp()

        assert app.window is None
