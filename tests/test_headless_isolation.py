"""The test harness must not be able to touch the real desktop session.

Running the suite used to unmount the developer's document portal. GTK is not
what did it: `dbus-run-session` inherits ``XDG_RUNTIME_DIR``, so anything on the
private bus that activated ``org.freedesktop.portal.Documents`` got a second
``xdg-document-portal`` pointed at the same ``/run/user/$UID/doc`` as the real
one. Its mount is ``auto_unmount``; when the test bus exited, it took the real
session's mount with it, and every flatpak on the machine then failed to launch.
The real ``xdg-document-portal.service`` reported ``active (running)`` the whole
time, having never been the process that died.

`scripts/headless-session.sh` is the fix, and these tests are what stops it
being taken back out. They assert on wiring rather than behaviour, because the
damage only happens on a machine with a real session -- CI has no portal to
break, so this is the only thing that can catch a regression there.
"""

import os
import re
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "scripts" / "headless-session.sh"

#: Everything that can start a bus: the Makefile, the packaging scripts and the
#: workflows. Anything spawning one outside the wrapper reopens the hole.
CALL_SITE_FILES = [
    ROOT / "Makefile",
    *sorted((ROOT / "packaging").glob("*.sh")),
    *sorted((ROOT / "scripts").glob("*.sh")),
    *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
]


def commands(path: Path) -> list[str]:
    """Lines of `path` with continuations joined and comments dropped.

    Joining matters: the wrapper sets the environment on one line and runs the
    bus on the next, and the point of the whole exercise is that those are the
    same command.
    """
    joined = path.read_text().replace("\\\n", " ")
    return [line for line in joined.splitlines() if not line.lstrip().startswith("#")]


class TestTheWrapperExists:
    def test_it_is_there_and_executable(self):
        assert WRAPPER.is_file(), "scripts/headless-session.sh is missing"
        mode = WRAPPER.stat().st_mode
        assert mode & stat.S_IXUSR, "the wrapper is not executable"

    def test_it_refuses_to_run_nothing(self):
        """A call site that loses its command should fail, not start a bus."""
        assert 'if [ "$#" -eq 0 ]' in WRAPPER.read_text()


class TestTheRuntimeDirectoryIsPrivate:
    @pytest.fixture
    def bus_command(self) -> str:
        lines = [line for line in commands(WRAPPER) if "dbus-run-session" in line]
        assert len(lines) == 1, f"expected one bus invocation, found {lines}"
        return lines[0]

    def test_it_is_set_around_the_bus(self, bus_command):
        """Not inside it, and not in conftest.py.

        By the time pytest runs, dbus-daemon is already up, and it starts
        activated services with its own environment rather than pytest's -- so
        the portal it spawns still aims at the real runtime directory. The
        variable has to be in place before the bus is.
        """
        assert "XDG_RUNTIME_DIR=" in bus_command, bus_command
        assert bus_command.index("XDG_RUNTIME_DIR=") < bus_command.index(
            "dbus-run-session"
        ), bus_command

    def test_it_is_not_merely_unset(self):
        """Unsetting it moves the mount rather than isolating it.

        g_get_user_runtime_dir() falls back to the user cache directory, and
        the portal turns up at ~/.cache/doc instead: xdg-desktop-portal#512,
        a known nuisance and not a fix.
        """
        script = WRAPPER.read_text()
        assert "-u XDG_RUNTIME_DIR" not in script
        assert "unset XDG_RUNTIME_DIR" not in script

    def test_it_is_made_per_run(self, bus_command):
        script = WRAPPER.read_text()
        assert "mktemp -d" in script
        assert re.search(r"^\s*chmod 700 ", script, re.MULTILINE), (
            "D-Bus rejects a runtime directory with looser modes"
        )
        assert '"$runtime"' in bus_command, bus_command

    def test_it_is_short_enough_for_a_socket(self):
        """Under the real runtime directory, not a pytest tmpdir.

        AF_UNIX paths stop near 108 bytes, and a bus socket under a long prefix
        fails in a way that looks like anything except a path length.
        """
        script = WRAPPER.read_text()
        assert '"${XDG_RUNTIME_DIR:-/tmp}"' in script, (
            "the private directory must sit under the real runtime dir, "
            "falling back to /tmp where there is none"
        )


class TestItCleansUpAfterItself:
    @pytest.fixture
    def script(self) -> str:
        return WRAPPER.read_text()

    def test_it_cleans_up_on_a_signal_too(self, script):
        """EXIT alone leaks the directory when a suite is interrupted."""
        traps = [
            line for line in commands(WRAPPER) if line.lstrip().startswith("trap ")
        ]
        installed = [line for line in traps if not line.lstrip().startswith("trap - ")]
        assert installed, "nothing is trapped; an interrupted run leaves the dir"
        for signal in ("EXIT", "INT", "TERM"):
            assert any(signal in line for line in installed), (
                f"{signal} is not trapped: {installed}"
            )

    def test_it_never_deletes_through_a_mount(self, script):
        """`rm -rf` over a live FUSE mount is how the real portal was emptied.

        The check reads the mount table rather than testing one known path: the
        portal's doc/ is what this exists for, but a suite run also brings up
        gvfsd-fuse under the same directory.
        """
        assert "/proc/self/mounts" in script
        assert "fusermount" in script, "a FUSE mount is not taken off with umount"
        assert "rm -rf" in script
        assert script.index("mounts_under") < script.index("rm -rf"), (
            "the mount check has to come before the removal"
        )


class TestTheDisplayIsolationSurvived:
    """A different problem, solved in the same place, and still needed.

    GDK ignores DISPLAY whenever WAYLAND_DISPLAY is set, so without this xvfb
    was started and the tests ran against the developer's own compositor.
    """

    def test_wayland_is_taken_out_of_the_environment(self):
        assert "-u WAYLAND_DISPLAY" in WRAPPER.read_text()

    def test_the_x11_backend_is_forced(self):
        assert "GDK_BACKEND=x11" in WRAPPER.read_text()

    def test_it_still_starts_an_x_server(self):
        assert "xvfb-run" in WRAPPER.read_text()


class TestEveryCallSiteGoesThroughIt:
    """The assertion that actually holds the line.

    Isolation nobody routes through is isolation that is not applied, and the
    failure it prevents is invisible until someone's flatpaks stop launching.
    """

    def test_the_makefile_runs_the_suite_through_it(self):
        makefile = (ROOT / "Makefile").read_text()
        assert "HEADLESS := ./scripts/headless-session.sh" in makefile
        for target in ("test:", "test-gui:"):
            assert target in makefile
        assert makefile.count("$(HEADLESS)") >= 2

    def test_the_sysext_test_runs_the_smoke_test_through_it(self):
        """The one that runs on a live desktop, with the most to lose."""
        script = (ROOT / "packaging" / "test-sysext.sh").read_text()
        assert "scripts/headless-session.sh packaging/smoke-test-install.sh" in script

    def test_ci_runs_every_suite_through_it(self):
        """Through the wrapper, or through a make target that uses it.

        Either is fine and both are checked -- what must not appear is a job
        running the suite some third way, which is what every one of these was
        before the wrapper existed.
        """
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        # The lookbehind keeps python3-pytest, a package in a dnf list, from
        # reading as an invocation of it.
        runs = [
            line
            for line in workflow.splitlines()
            if not line.lstrip().startswith("#")
            and (
                re.search(r"(?<![-\w])pytest\b", line)
                or "smoke-test-install.sh" in line
            )
        ]
        assert runs, "no test invocations found in ci.yml"
        for line in runs:
            assert "scripts/headless-session.sh" in line or re.search(
                r"\bmake\s+test", line
            ), line

    @pytest.mark.parametrize(
        "path",
        [p for p in CALL_SITE_FILES if p != WRAPPER],
        ids=lambda p: str(p.relative_to(ROOT)),
    )
    def test_nothing_else_spawns_a_bus(self, path):
        if not path.is_file():
            pytest.skip(f"{path} is not present")
        offenders = [line for line in commands(path) if "dbus-run-session" in line]
        assert offenders == [], (
            f"{path.relative_to(ROOT)} starts its own bus instead of going "
            f"through scripts/headless-session.sh: {offenders}"
        )


class TestTheRunItselfIsIsolated:
    """And, when the suite runs under the wrapper, that it took effect."""

    def test_the_runtime_directory_is_not_the_session_one(self):
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if runtime is None or "gtkpass-session." not in runtime:
            pytest.skip("not running under scripts/headless-session.sh")
        assert Path(runtime).is_dir()
        assert runtime != f"/run/user/{os.getuid()}", (
            "the tests are using the real runtime directory"
        )
