"""Entry point for the frozen Windows build, and the way to check one.

PyInstaller freezes a script rather than a console-script entry point, so this
is the one file the bundle exists to run. Started with no arguments it does
exactly what the ``gtkpass`` command does, and nothing else.

``--self-check FILE`` is the other half, and it is here for a reason worth
writing down. Everywhere else this project tests a package by installing it and
running Python against it -- see ``packaging/smoke-test-install.sh``, which is
what CI runs after ``dnf install``. A frozen bundle has no interpreter to run
anything against: the interpreter is inside it, reachable only by starting the
executable. So the checks that script makes from the outside have to be made
from the inside, and this is the inside.

They are written to a file rather than printed because a windowed build has no
console attached and Python's own stdout goes nowhere. The exit code is the
verdict; the file says what happened.
"""

import sys
import traceback
from pathlib import Path


def _self_check(report_path: str) -> int:
    """Report on everything packaging can get wrong. See the module docstring."""
    lines: list[str] = []
    failures: list[str] = []

    def check(description, probe):
        try:
            detail = probe()
        except Exception:
            failures.append(description)
            lines.append(f"FAIL {description}")
            lines.extend("     " + line for line in traceback.format_exc().splitlines())
        else:
            lines.append(f"ok   {description}: {detail}")

    def it_is_a_bundle():
        from gtkpass import frozen

        assert frozen.is_frozen(), "not running frozen"
        root = frozen.bundle_root()
        assert root is not None and root.is_dir(), f"no bundle root: {root}"
        return root

    def the_guard_allows_the_store():
        # The no-launcher design in two assertions, as the RPM's smoke test puts
        # it. An installed application that thinks it is a checkout refuses its
        # owner's store and loads no backends at all.
        from gtkpass import safety

        assert not safety.running_from_checkout(), "a bundle looks like a checkout"
        assert safety.opted_in(), "a bundle would refuse the real store"
        return "installed build, store allowed"

    def the_schema_resolves():
        # A value from the schema rather than merely a Settings object: a schema
        # that compiled but lost its keys would still hand one of those back.
        from gtkpass import config

        timeout = config.get_settings().get_int("clipboard-timeout")
        assert timeout > 0, f"clipboard-timeout = {timeout}"
        return f"clipboard-timeout = {timeout}"

    def gtk_found_its_own_schemas():
        # Separately from this application's, and not out of tidiness. GTK looks
        # its own settings up on paths a file dialog reaches, and a lookup that
        # misses calls g_error(): the process aborts, with no traceback, no
        # exception and nothing written down. Finding that out here costs a
        # build; finding it out later costs a user their session.
        from gtkpass._gi import Gio

        source = Gio.SettingsSchemaSource.get_default()
        assert source is not None, "no default schema source at all"
        wanted = "org.gtk.gtk4.Settings.FileChooser"
        assert source.lookup(wanted, True) is not None, f"{wanted} is missing"
        return wanted

    def the_backends_are_discoverable():
        # Read out of the .dist-info the bundle carries. Without that metadata
        # this finds nothing and the application starts empty.
        from gtkpass.backends.manager import BackendManager

        found = sorted(b.__name__ for b in BackendManager().discover_backends())
        expected = [
            "DemoBackend",
            "DirectBackend",
            "PassBackend",
            "SecretServiceBackend",
        ]
        assert found == expected, f"expected {expected}, found {found}"
        return ", ".join(found)

    def the_demo_backend_reads_its_data():
        from gtkpass.backends.demo import DemoBackend

        backend = DemoBackend.create()
        entries = backend.list_passwords()
        assert entries, "demo backend listed nothing"
        assert backend.get_password(entries[0].name).password, "no password decoded"
        return f"{len(entries)} entries, first one decodes"

    def the_ui_templates_load():
        # The .ui files travel inside the wheel and are read through
        # importlib.resources. Left out, they are missing at run time and
        # nowhere else. Building a widget is what proves they arrived -- and it
        # is also the only check here that needs GTK to actually initialise.
        from gtkpass._gi import Adw

        Adw.init()

        from gtkpass.ui.password_detail import PasswordDetailView

        assert PasswordDetailView() is not None
        return "password_detail.ui loaded and instantiated"

    def the_icon_travelled():
        from gtkpass import frozen

        root = frozen.bundle_root()
        icon = (
            root
            / "share/icons/hicolor/scalable/apps"
            / "io.github.RonnyPfannschmidt.GTKPass.svg"
        )
        assert icon.is_file(), f"missing {icon}"
        return str(icon)

    check("it is a bundle", it_is_a_bundle)
    check("the safety guard allows the real store", the_guard_allows_the_store)
    check("the GSettings schema resolves", the_schema_resolves)
    check("GTK found its own schemas", gtk_found_its_own_schemas)
    check("the backends are discoverable", the_backends_are_discoverable)
    check("the demo backend reads its packaged data", the_demo_backend_reads_its_data)
    check("the packaged UI templates load", the_ui_templates_load)
    check("the application icon travelled", the_icon_travelled)

    if failures:
        lines.append("")
        lines.append(f"{len(failures)} check(s) failed: {', '.join(failures)}")

    Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures else 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        return _self_check(sys.argv[2])

    from gtkpass.__main__ import main as app_main

    return app_main()


if __name__ == "__main__":
    sys.exit(main())
