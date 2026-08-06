"""Cheap whole-package checks.

Every test here exists because something in this repository broke in a way that
none of the previous tests could see.  Keep them fast and keep them blunt.
"""

import importlib
import importlib.metadata
import importlib.resources
import pkgutil

import pytest

import gtkpass

MODULE_NAMES = sorted(
    module.name for module in pkgutil.walk_packages(gtkpass.__path__, prefix="gtkpass.")
)


def test_walk_packages_finds_modules():
    """Guard against the parametrisation below silently collecting nothing."""
    assert len(MODULE_NAMES) > 5, MODULE_NAMES


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_module_imports(module_name, monkeypatch, tmp_path):
    """Every module must import cleanly from an arbitrary directory.

    Catches syntax errors, circular imports, and resources addressed by a
    path relative to the current working directory.
    """
    monkeypatch.chdir(tmp_path)
    importlib.import_module(module_name)


class TestPackagedResources:
    """The UI definitions and demo data must travel with the package."""

    @pytest.mark.parametrize(
        ("package", "resource"),
        [
            ("gtkpass.ui.blueprints", "window.ui"),
            ("gtkpass.ui.blueprints", "password_list.ui"),
            ("gtkpass.ui.blueprints", "password_detail.ui"),
            ("gtkpass.ui.blueprints", "password_edit.ui"),
            ("gtkpass.backends.data", "demo.json"),
        ],
    )
    def test_resource_is_reachable(self, package, resource):
        assert (importlib.resources.files(package) / resource).is_file()

    @pytest.mark.parametrize(
        "package", ["gtkpass.ui.blueprints", "gtkpass.backends.data"]
    )
    def test_resource_dir_is_a_real_package(self, package):
        """Namespace packages are not picked up by setuptools' package finder.

        Without an ``__init__.py`` these directories are omitted from the built
        wheel entirely, so the resources above resolve only in an editable
        install.
        """
        module = importlib.import_module(package)
        assert module.__file__ is not None, (
            f"{package} is a namespace package; add an __init__.py or it will "
            f"be missing from the wheel"
        )
