#!/usr/bin/env bash
# Check that an *installed* GTKPass works, as installed.
#
# Run it against a system where the package is already in place -- CI does this
# straight after `dnf install`, and packaging/test-sysext.sh after merging the
# extension. Needs a display and a session bus; both callers wrap it in
# `xvfb-run -a dbus-run-session --`.
#
# What it is looking for is the class of breakage a build cannot see: a wheel
# that installed without its .ui files, a schema that never reached the compiled
# cache, entry points that resolve to nothing, and the guard refusing the store
# because it thinks a packaged build is somebody's checkout.
set -euo pipefail

echo "==> gtkpass is on PATH"
command -v gtkpass

# From /, so a checkout in the working directory cannot be what gets imported.
# The whole point here is to exercise the installed copy.
cd /

echo "==> the installed copy is what imports"
python3 - <<'PY'
import sys
from pathlib import Path

import gtkpass
import gtkpass.safety as safety

location = Path(gtkpass.__file__).resolve()
print(f"    {location}")
assert "site-packages" in location.parts, f"not an installed copy: {location}"

# The no-wrapper design in one assertion. If this is false, an installed build
# refuses its owner's store and every backend fails to load -- which is exactly
# what a launcher script would have been written to paper over.
assert not safety.running_from_checkout(), "installed build looks like a checkout"
assert safety.opted_in(), "installed build would refuse the real store"
print("    guard: installed build, store allowed")

sys.exit(0)
PY

echo "==> the GSettings schema resolves"
python3 - <<'PY'
from gtkpass import config

settings = config.get_settings()
# A value from the schema rather than merely a Settings object: a schema that
# compiled but lost its keys would still hand one of those back.
print(f"    clipboard-timeout = {settings.get_int('clipboard-timeout')}")
assert settings.get_int("clipboard-timeout") > 0
PY

echo "==> all four backends are discoverable"
python3 - <<'PY'
from gtkpass.backends.manager import BackendManager

found = sorted(backend.__name__ for backend in BackendManager().discover_backends())
print(f"    {found}")
expected = ["DemoBackend", "DirectBackend", "PassBackend", "SecretServiceBackend"]
assert found == expected, f"expected {expected}, found {found}"
PY

echo "==> the packaged UI resources load"
# The .ui files travel inside the wheel and are read through
# importlib.resources. Left out of the package data they are missing at run
# time and nowhere else, and the application dies on import of the first
# template. Building a widget is what proves they arrived.
python3 - <<'PY'
from gtkpass._gi import Adw

Adw.init()

from gtkpass.ui.password_detail import PasswordDetailView  # noqa: E402

view = PasswordDetailView()
assert view is not None
print("    password_detail.ui loaded and instantiated")
PY

echo "==> the demo backend reads its packaged data"
python3 - <<'PY'
from gtkpass.backends.demo import DemoBackend

backend = DemoBackend.create()
entries = backend.list_passwords()
assert entries, "demo backend listed nothing"
entry = backend.get_password(entries[0].name)
assert entry.password, "demo entry had no password"
print(f"    {len(entries)} demo entries, first one decodes")
PY

echo "==> the desktop files are where the shell looks for them"
test -f /usr/share/applications/io.github.RonnyPfannschmidt.GTKPass.desktop
test -f /usr/share/metainfo/io.github.RonnyPfannschmidt.GTKPass.metainfo.xml
test -f /usr/share/icons/hicolor/scalable/apps/io.github.RonnyPfannschmidt.GTKPass.svg

# Only where the validators happen to be present. They are build dependencies,
# so CI has them; a desktop that merged the sysext to try it out has no reason
# to, and their absence is not a failure of the thing under test.
if command -v desktop-file-validate >/dev/null; then
    desktop-file-validate \
        /usr/share/applications/io.github.RonnyPfannschmidt.GTKPass.desktop
fi
if command -v appstream-util >/dev/null; then
    appstream-util validate-relax --nonet \
        /usr/share/metainfo/io.github.RonnyPfannschmidt.GTKPass.metainfo.xml
fi

echo
echo "==> installed package works"
