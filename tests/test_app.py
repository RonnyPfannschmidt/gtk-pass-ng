"""Unit tests for the main application."""

import pytest


@pytest.mark.unit
class TestGTKPassApp:
    """Test cases for the GTKPass application."""

    @pytest.mark.skipif(
        not pytest.importorskip("gi.repository.Gtk", minversion="4.0"),
        reason="GTK4 not available",
    )
    def test_app_initialization(self):
        """Test that the GTKPass application can be initialized."""
        from gtkpass.app import GTKPassApp

        app = GTKPassApp()
        assert app is not None
        assert app.window is None  # Window not created until activated
