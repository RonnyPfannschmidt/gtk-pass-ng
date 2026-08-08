"""UI definitions belong in Blueprint files, not in Python.

Widget trees built by hand drift from the .blp files, cannot be previewed, and
are what this project spent its first months accumulating. This test fails if
any new widget construction appears in Python.
"""

import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src" / "gtkpass"

#: Types that are not widgets and have no place in a UI definition: models,
#: actions, flags and other plumbing that a .blp file cannot express.
NON_WIDGET_TYPES = {
    "Adjustment",
    "Template",  # the decorator that loads a .blp-derived .ui
    "ListStore",
    "NoSelection",
    "SingleSelection",
    "StringList",
    "TreeListModel",
    "TreeStore",
    "Variant",
    "SimpleAction",
    "SimpleActionGroup",
    "Settings",
    "Builder",
    "ContentProvider",
    "CssProvider",
    "EventControllerKey",
    "GestureClick",
    "Shortcut",
    "ShortcutController",
}


def python_files():
    """Project sources only; never a stray environment inside the tree."""
    return sorted(
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if not any(part.startswith(".") for part in path.parts)
    )


def widget_constructions(path: Path):
    """Find ``Gtk.Foo(...)`` / ``Adw.Foo(...)`` calls that build a widget."""
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match Namespace.TypeName(...), not Namespace.Type.method(...)
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
            continue
        if func.value.id not in {"Gtk", "Adw"}:
            continue
        name = func.attr
        if not name[0].isupper() or name in NON_WIDGET_TYPES:
            continue
        found.append(f"{func.value.id}.{name} at line {node.lineno}")
    return found


@pytest.mark.parametrize("path", python_files(), ids=lambda p: p.name)
def test_no_widgets_are_built_in_python(path):
    constructions = widget_constructions(path)

    assert constructions == [], (
        f"{path.relative_to(SOURCE_ROOT)} builds widgets in Python: "
        f"{constructions}. Declare them in a .blp file and load the template "
        f"instead. If this is genuinely not a widget, add it to "
        f"NON_WIDGET_TYPES."
    )


def test_every_blueprint_has_a_compiled_ui():
    """A .blp with no .ui beside it never reaches the application."""
    blueprints = SOURCE_ROOT / "ui" / "blueprints"
    missing = [
        source.name
        for source in blueprints.glob("*.blp")
        if not source.with_suffix(".ui").is_file()
    ]

    assert missing == [], f"run 'make ui' to compile: {missing}"
