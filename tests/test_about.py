"""The About dialog: the one place the application says which build it is."""

import pytest

pytestmark = pytest.mark.gui


class TestTheVersion:
    def test_it_is_the_version_of_the_installed_distribution(self):
        """It said "unknown" in every build, installed or not.

        The lookup asked for a distribution called ``gtkpass``, which is the
        import name and the command. The distribution is ``gtk-pass-ng``,
        because PyPI holds the other name for an unrelated project.
        """
        import importlib.metadata

        from gtkpass.ui.about import _version

        assert _version() == importlib.metadata.version("gtk-pass-ng")
