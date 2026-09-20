"""How the project spells the interpreter it builds and tests against.

PyGObject and pycairo come from the distribution, so the environment has to be
created against an interpreter that already has them. That was hardcoded to
``/usr/bin/python3``, which is right on most machines and quietly wrong on one
whose bindings belong to a different minor version -- and quietly is the whole
problem, since the answer arrives much later as an ImportError from inside the
application.

`scripts/system-python.sh` asks instead, and `make test PYTHON=...` is the other
half: one definition of "run the suite" that the development environment, an
installed wheel and an installed RPM can all be pointed at, rather than three
spellings in three places, one of which is a CI workflow nobody reads until it
breaks.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SELECT = ROOT / "scripts" / "system-python.sh"
MAKEFILE = ROOT / "Makefile"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("bash") is None,
    reason="the toolchain scripts are for the Linux development environment",
)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SELECT), *args], capture_output=True, text=True, check=False
    )


def split_jobs(workflow: str) -> dict[str, str]:
    """The workflow's jobs, by name. Two-space keys under `jobs:` are jobs."""
    jobs: dict[str, str] = {}
    name: str | None = None
    body: list[str] = []
    for line in workflow.split("\njobs:\n", 1)[1].splitlines():
        header = re.match(r"^  ([\w-]+):\s*$", line)
        if header:
            if name:
                jobs[name] = "\n".join(body)
            name, body = header.group(1), []
        elif name:
            body.append(line)
    if name:
        jobs[name] = "\n".join(body)
    return jobs


def is_install_line(line: str) -> bool:
    """Whether a line starts a package installation.

    Both package managers, because the Linux jobs are no longer all Fedora:
    the Debian and Ubuntu ones say apt-get. Reading only dnf did not report a
    job's packages as missing -- it reported the job as having none at all,
    which the checks below then passed silently.
    """
    return (" install" in line) and ("dnf " in line or "apt-get " in line)


def installed_packages(job: str) -> set[str]:
    """What a job's install lines name, continuations included."""
    packages: set[str] = set()
    collecting = False
    for line in job.splitlines():
        if is_install_line(line):
            collecting = True
            line = line.split(" install", 1)[1]
        elif not collecting:
            continue
        packages.update(word for word in line.split() if not word.startswith("-"))
        collecting = line.rstrip().endswith("\\")
    # The trailing backslash of a continued line is a word of its own, and
    # rstripping it leaves an empty one behind.
    return {stripped for package in packages if (stripped := package.rstrip("\\"))}


class TestChoosingTheInterpreter:
    def test_the_script_is_there_and_executable(self):
        assert SELECT.is_file(), "scripts/system-python.sh is missing"
        assert SELECT.stat().st_mode & 0o111, "the script is not executable"

    def test_it_names_one_that_has_the_bindings(self):
        """The check that matters: what it prints must actually import gi."""
        chosen = run().stdout.strip()
        assert chosen, "no interpreter was chosen"

        proof = subprocess.run(
            [chosen, "-c", "import gi"], capture_output=True, text=True, check=False
        )
        assert proof.returncode == 0, f"{chosen} cannot import gi: {proof.stderr}"

    def test_it_names_an_absolute_path(self):
        """Not `python3` off PATH.

        Whatever pyenv, conda or a uv toolchain has put in front is somebody
        else's interpreter, and a uv-managed one's site-packages is precisely
        the one without the distribution's bindings.
        """
        assert run().stdout.strip().startswith("/")

    def test_an_explicit_choice_is_taken(self):
        result = run(sys.executable)

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == sys.executable

    def test_an_explicit_choice_is_checked_rather_than_trusted(self, tmp_path):
        """Naming the wrong interpreter earns the same answer as having none.

        Taken on trust, it produces an environment that builds and then fails
        from inside the application, which is the failure this exists to stop.
        """
        stub = tmp_path / "python3"
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(0o755)

        result = run(str(stub))

        assert result.returncode != 0
        assert "cannot import gi" in result.stderr
        assert "python3-gobject" in result.stderr, "it should say what to install"

    def test_no_argument_is_not_an_argument(self):
        """The Makefile passes an unset SYSTEM_PYTHON as an empty word."""
        assert run("").returncode == 0

    def test_pycairo_is_preferred_and_not_required(self, tmp_path):
        """PyGObject has not depended on it for some releases.

        Debian's python3-gi does not pull a python3-cairo, and the documented
        apt line does not name one either, so insisting would refuse to build
        an environment that works.
        """
        stub = tmp_path / "python3"
        stub.write_text(
            '#!/bin/sh\ncase "$2" in *cairo*) exit 1 ;; *) exit 0 ;; esac\n'
        )
        stub.chmod(0o755)

        result = run(str(stub))

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(stub)


class TestOneDefinitionOfRunningTheSuite:
    """`test` takes an interpreter, so CI can run the target rather than copy it.

    The top of the Makefile says CI runs these same targets so there is one
    definition rather than two that drift. That was true of `check` and untrue
    of the tests, which CI spelled out by hand in three places.
    """

    @pytest.fixture
    def makefile(self) -> str:
        return MAKEFILE.read_text()

    def test_the_suite_runs_against_a_chosen_interpreter(self, makefile):
        assert "$(HEADLESS) $(PYTHON) -m pytest" in makefile

    def test_the_default_is_the_development_environment(self, makefile):
        assert "PYTHON := uv run python" in makefile, (
            "assigned rather than defaulted, so an exported PYTHON cannot "
            "redirect the suite; a command-line override still wins"
        )

    def test_the_environment_is_built_on_the_chosen_interpreter(self, makefile):
        """`make sync` must not hardcode one either."""
        assert "./scripts/system-python.sh" in makefile
        hardcoded = [
            line
            for line in makefile.splitlines()
            if re.match(r"\s*SYSTEM_PYTHON\s*[:?]?=\s*\S", line)
        ]
        assert hardcoded == [], (
            f"the interpreter is chosen by the script, not written in: {hardcoded}"
        )

    @pytest.mark.parametrize("target", ["test", "test-gui", "test-wheel"])
    def test_the_target_is_declared_phony(self, makefile, target):
        phony = makefile.split(".PHONY:", 1)[1].split("\n\n", 1)[0]
        assert target in phony.split()


class TestReadingWhatAJobInstalls:
    """The checks below are only as good as this, and it fails open.

    A job whose install line it cannot read has no packages as far as it is
    concerned, and every assertion about what a job installs then passes.
    """

    def test_a_dnf_line_with_continuations(self):
        job = """
      - name: install dependencies
        run: |
          dnf -y --setopt=install_weak_deps=False install \\
            make git-core python3-pytest
"""
        assert installed_packages(job) == {"make", "git-core", "python3-pytest"}

    def test_an_apt_line_too(self):
        """Debian and Ubuntu are Linux jobs the same as the Fedora ones."""
        job = """
      - name: install dependencies
        run: |
          apt-get install -y --no-install-recommends \\
            make git python3-pytest
"""
        assert installed_packages(job) == {"make", "git", "python3-pytest"}


class TestAContainerJobCanReachGitHub:
    """`actions/checkout` fetches over HTTPS, and the Debian images ship no CA
    bundle.

    Without ca-certificates git stops at "Problem with the SSL CA cert (path?
    access rights?)" during checkout -- before a single step of the job's own
    work has run. The job then fails for a reason that has nothing to do with
    what it tests, which is how `tests, installed deb` ran red from the day it
    was added without ever having executed a test. The Fedora images carry the
    bundle already, so this is only about the apt ones.
    """

    @pytest.fixture
    def jobs(self) -> dict[str, str]:
        return split_jobs(WORKFLOW.read_text())

    def test_every_apt_job_that_checks_out_installs_ca_certificates(self, jobs):
        missing = sorted(
            name
            for name, body in jobs.items()
            if "apt-get" in body
            and "actions/checkout" in body
            and "ca-certificates" not in installed_packages(body)
        )
        assert missing == [], (
            f"these jobs check out over HTTPS with no CA bundle: {missing}"
        )

    def test_the_check_would_notice(self, jobs):
        """The assertion above passes vacuously if the jobs stop being found."""
        candidates = [
            name
            for name, body in jobs.items()
            if "apt-get" in body and "actions/checkout" in body
        ]
        assert len(candidates) >= 2, f"expected the apt jobs, found {candidates}"


class TestCIRunsTheseTargets:
    @pytest.fixture
    def workflow(self) -> str:
        return WORKFLOW.read_text()

    def test_the_suite_is_never_spelled_out_by_hand(self, workflow):
        """A pytest invocation here is a second definition, and it drifts."""
        offenders = [
            line
            for line in workflow.splitlines()
            if "-m pytest" in line and not line.lstrip().startswith("#")
        ]
        assert offenders == [], offenders

    def test_the_wheel_is_tested_through_the_target(self, workflow):
        assert "make test-wheel" in workflow

    def test_the_rpm_is_tested_through_the_target(self, workflow):
        assert "make test PYTHON=python3" in workflow

    def test_every_package_ci_builds_reaches_the_release(self, workflow):
        """A package built here and not collected there is one the release
        goes out without, quietly.

        Nothing says so at the time: the jobs are green, the release exists,
        and the file is simply not among its assets. It is the person who
        goes looking for it weeks later who finds out.
        """
        kinds = set(re.findall(r"dist/[\w/*.-]*\*[\w.-]*\.(\w+)", workflow))
        assert kinds, "no artefact paths found; this check would pass on nothing"

        release = (WORKFLOW.parent / "release.yml").read_text()
        collected = release.split("collect what to publish", 1)[1].split(
            "- name: write the notes", 1
        )[0]

        for kind in sorted(kinds):
            assert f".{kind}" in collected, (
                f"CI builds a .{kind} and the release does not collect it"
            )

    def test_the_jobs_that_call_make_install_it(self, workflow):
        """A container image that has no make cannot run a Makefile target.

        Nothing about the failure points at this: the step reports `make: not
        found` from a job whose dnf line looks complete.
        """
        for name, job in split_jobs(workflow).items():
            if not re.search(r"run: make\b|make test\b", job):
                continue
            if "container:" not in job:
                continue
            assert "make" in installed_packages(job), (
                f"the {name} job runs make and does not install it"
            )


class TestRunningAPackageBuildsItFirst:
    """`make flatpak-run` used to run whatever was installed last.

    Which is a quiet wrong answer rather than a failure: you change something,
    build nothing, run the Flatpak, and are looking at the previous build while
    believing you are looking at your change. The command that fails to
    reproduce a bug then also fails to reproduce a fix, and there is nothing on
    screen to say which build is on screen.

    A stamp rather than an unconditional rebuild, so this costs nothing when
    nothing changed -- the RPM and the .deb already work this way and the
    Flatpak was the one that did not.
    """

    def dry_run(self, *args: str) -> str:
        """What make *would* do, without doing any of it."""
        result = subprocess.run(
            ["make", "--dry-run", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout

    @pytest.fixture
    def everything_out_of_date(self) -> str:
        """--always-make, so the answer does not depend on this machine.

        Whether a stamp happens to exist in this checkout is not what is under
        test; that the target has one at all is.
        """
        return "--always-make"

    def test_running_the_flatpak_builds_it(self, everything_out_of_date):
        planned = self.dry_run(everything_out_of_date, "flatpak-run")

        assert "flatpak-builder" in planned, (
            f"make flatpak-run runs the previously installed build: {planned.strip()}"
        )

    def test_running_the_flatpak_still_runs_it(self, everything_out_of_date):
        planned = self.dry_run(everything_out_of_date, "flatpak-run")

        assert "flatpak run" in planned

    def test_the_flatpak_build_recompiles_the_blueprints(self, everything_out_of_date):
        """The .ui files are what the manifest copies in.

        A .blp edited without `make ui` is an application whose interface is the
        previous one -- built, installed, and indistinguishable from the current
        one until something is clicked.
        """
        planned = self.dry_run(everything_out_of_date, "flatpak-run")

        assert "blueprint-compiler" in planned

    def test_a_failed_build_does_not_leave_its_build_dir_behind(
        self, everything_out_of_date
    ):
        """flatpak-builder removes build directories on success only.

        A build interrupted or failed leaves its module tree in
        .flatpak-builder/build, and nothing ever comes back for it -- two of
        them had accumulated to half a gigabyte before anyone looked, one of
        them months old. --delete-build-dirs removes them either way.

        The module cache is a different directory and is not affected; that one
        is what keeps a rebuild at twelve seconds instead of compiling git.
        """
        planned = self.dry_run(everything_out_of_date, "flatpak")

        assert "--delete-build-dirs" in planned

    def test_nothing_is_rebuilt_when_nothing_changed(self):
        """The stamp is the point: this has to stay cheap enough to always run.

        A target that rebuilt unconditionally would be correct and unused --
        `flatpak run` on its own is shorter to type, and that is the habit this
        is meant to replace.
        """
        stamp = ROOT / "dist" / "flatpak" / ".installed"
        # The time is restored, not just the file. Touching a stamp that was
        # already there tells the next `make flatpak` that the installed build
        # is current, so it installs nothing and `make flatpak-run` launches
        # the previous build -- this class's own failure, reintroduced by the
        # test for it, on every developer who ran the suite before building.
        was = stamp.stat().st_mtime_ns if stamp.exists() else None
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
        try:
            planned = self.dry_run("flatpak-run")
        finally:
            if was is None:
                stamp.unlink()
            else:
                os.utime(stamp, ns=(was, was))

        assert "flatpak-builder" not in planned, (
            f"an up-to-date Flatpak was rebuilt anyway: {planned.strip()}"
        )
        assert "flatpak run" in planned
