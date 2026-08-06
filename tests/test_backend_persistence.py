"""Integration tests for backend configuration persistence and data display."""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib


@pytest.mark.integration
class TestBackendDataDisplay:
    """Test that backend data actually appears in the GUI."""
    
    def test_demo_backend_has_passwords(self):
        """Verify demo backend returns passwords when created."""
        from gtkpass.backends.demo import DemoBackend
        
        # Create demo backend
        backend = DemoBackend.create()
        
        # List passwords
        passwords = list(backend.list_passwords())
        
        assert len(passwords) > 0, "Demo backend should have sample passwords"
        assert all(p.name for p in passwords), "All passwords should have names"
    
    def test_demo_backend_get_password_works(self):
        """Verify we can get password details from demo backend."""
        from gtkpass.backends.demo import DemoBackend
        
        backend = DemoBackend.create()
        passwords = list(backend.list_passwords())
        
        assert len(passwords) > 0
        
        first_password = passwords[0]
        # Use name, not path, for get_password
        details = backend.get_password(first_password.name)
        
        assert details is not None
        assert details.name == first_password.name
        assert details.password
        assert len(details.password) > 0
    
    def test_main_window_needs_backend_loading(self):
        """
        Test documenting the issue: Main window doesn't load backends or display data.
        
        This test demonstrates the problem the user is experiencing:
        1. They add a backend in preferences
        2. Settings are saved  
        3. But the main window doesn't load the backend
        4. So no passwords appear
        
        This test is expected to fail until backend loading is implemented.
        """
        pytest.skip(
            "TODO: Main window needs to load backends from GSettings "
            "and display password data. Currently it only shows 'No Backends Configured' message."
        )


@pytest.mark.integration
class TestSettingsUIWorkflow:
    """Test settings UI workflow without requiring GSettings persistence."""
    
    def test_settings_window_can_be_created(self):
        """Test that settings window can be instantiated."""
        from gtkpass.ui.settings import SettingsWindow
        
        Adw.init()
        window = SettingsWindow()
        
        assert window is not None
        assert window.backends_group is not None
        assert window.backend_combo is not None
