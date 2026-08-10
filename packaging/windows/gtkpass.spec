# PyInstaller spec for the Windows build.  Driven by packaging/windows/build.ps1.
#
# A spec is executed by PyInstaller with Analysis, EXE and COLLECT already in
# scope, so it is not an importable module and nothing else should treat it as
# one.  Its inputs arrive through the environment rather than as arguments,
# which is all PyInstaller offers a spec.
#
# What this has to get right that a plain `pyinstaller gtkpass-launcher.py`
# would not:
#
#   * Gtk 4.0.  PyInstaller's gi hook defaults to Gtk 3.0 and silently collects
#     nothing when that is absent, leaving a bundle that fails at gi.require_version.
#   * The distribution metadata.  Backends are discovered through the
#     `gtkpass.backends` entry point group, which is read out of the installed
#     .dist-info; without it the application starts with no backends at all and
#     nothing in the log to say why.
#   * The backend modules themselves.  Nothing imports them -- the entry point
#     names them as a string -- so PyInstaller's import graph never sees them.
#   * The compiled schema and the icon theme, staged by build.ps1 and picked up
#     here as a directory tree.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

REPO_ROOT = Path(os.environ["GTKPASS_REPO_ROOT"])
STAGING = Path(os.environ["GTKPASS_STAGING"])
ICON = REPO_ROOT / "data" / "icons" / "io.github.RonnyPfannschmidt.GTKPass.ico"

datas = [
    # The .ui templates and demo.json, loaded through importlib.resources.
    *collect_data_files("gtkpass"),
    # Entry points, and what safety.require_installed() reads.
    *copy_metadata("gtk-pass-ng"),
    # share/glib-2.0/schemas and share/icons, as assembled by build.ps1.
    # gtkpass.frozen points GLib at the first; PyInstaller's own glib runtime
    # hook puts the whole of share/ on XDG_DATA_DIRS, which covers the second.
    (str(STAGING / "share"), "share"),
]

analysis = Analysis(  # noqa: F821  -- injected by PyInstaller
    [str(REPO_ROOT / "packaging" / "windows" / "gtkpass-launcher.py")],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("gtkpass"),
    hookspath=[],
    hooksconfig={
        "gi": {
            "module-versions": {"Gtk": "4.0"},
            # Adwaita alone. The hook otherwise collects every icon theme the
            # build machine has, which for the gvsbuild tree is only Adwaita
            # and hicolor anyway -- naming them keeps that true if it changes.
            "icons": ["Adwaita", "hicolor"],
            "themes": [],
            # No translations are shipped: this application has none of its own
            # yet, and GTK's would be some 40 MB of catalogues for an interface
            # that is still in English.
            "languages": ["en"],
        },
    },
    excludes=[
        # The Secret Service is Linux-only and the backend guards its import;
        # naming it here keeps a stray copy on the build machine from being
        # collected into a bundle where it cannot work.
        "secretstorage",
        "jeepney",
        "tkinter",
    ],
    noarchive=False,
)

pyz = PYZ(analysis.pure)  # noqa: F821  -- injected by PyInstaller

exe = EXE(  # noqa: F821  -- injected by PyInstaller
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="gtkpass",
    debug=False,
    strip=False,
    upx=False,
    # A password manager that opens a console window behind itself every time
    # it starts is not a finished application. GLib still writes its own
    # diagnostics to the standard handles, so `gtkpass.exe --help > out.txt`
    # from a shell continues to work; only Python's own stdout is discarded.
    console=False,
    icon=str(ICON),
)

COLLECT(  # noqa: F821  -- injected by PyInstaller
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="gtkpass",
)
