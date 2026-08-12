"""The Debian package, and the two places it disagrees with the RPM.

The .deb is built from the same sdist as the RPM and installs the same files,
so almost nothing here is about Debian as such. What is: the interpreter's
directory is called ``dist-packages`` rather than ``site-packages``, and the
dependency floors are written twice -- once as Fedora package names in
gtkpass.spec, once as GIR package names in debian/control -- which is a fact
that can drift and so is checked rather than trusted.

The version tests are the ones that earn their place. A snapshot has to sort
against the release it is a snapshot of, in the right direction, and dpkg's
ordering is not rpm's: `~` sorts before nothing and `+` after it. Getting that
backwards produces a package that installs, works, and then refuses to be
upgraded by the actual release -- which nothing notices until the release.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
DEBIAN = PACKAGING / "debian"
SPEC = PACKAGING / "gtkpass.spec"
SMOKE_TEST = PACKAGING / "smoke-test-install.sh"
DEB_VERSION = PACKAGING / "deb-version.sh"

#: The distribution, and the package it installs. Only the name it is
#: distributed under differs from the import package; see pyproject.toml.
SOURCE_PACKAGE = "gtk-pass-ng"
BINARY_PACKAGE = "gtkpass"


class TestTheInstalledCopyIsRecognisedOnDebian:
    """The smoke test asks whether what imported is the installed copy.

    It asked by looking for ``site-packages`` in the path, which is every
    layout except the one Debian uses: a .deb installs into
    ``/usr/lib/python3/dist-packages``. The check failed there on a package
    that was in every other respect correct.
    """

    def test_the_smoke_test_accepts_both_layouts(self):
        script = SMOKE_TEST.read_text()

        assert "not an installed copy" in script, "the check itself is gone"
        assert "dist-packages" in script, "a Debian install is not a checkout"
        assert "site-packages" in script, "and the other layouts still count"


class TestTheSourcePackage:
    def test_the_debian_directory_is_there(self):
        assert DEBIAN.is_dir(), "packaging/debian/ is missing"

    @pytest.mark.parametrize(
        "name", ["control", "rules", "copyright", "changelog.in", "source/format"]
    )
    def test_the_file_is_present(self, name):
        assert (DEBIAN / name).is_file(), f"missing packaging/debian/{name}"

    def test_the_changelog_itself_is_generated(self):
        """Its top entry is what dpkg takes the version from, and that version
        comes from git -- so a copy kept here is wrong from the next commit
        onwards, and wrong quietly. build-deb.sh writes it from changelog.in.
        """
        assert not (DEBIAN / "changelog").exists(), (
            "a checked-in changelog is a second place the version lives"
        )

    def test_the_rules_file_is_executable(self):
        """dpkg-buildpackage runs it as a program, not through make."""
        assert (DEBIAN / "rules").stat().st_mode & 0o111

    def test_the_source_format_is_quilt(self):
        """Built from the sdist, which is the thing actually distributed.

        A native package would be built from the checkout instead, and would
        never exercise the tarball a release publishes.
        """
        assert (DEBIAN / "source" / "format").read_text().strip() == "3.0 (quilt)"


class TestTheNamesMatchTheRestOfThePackaging:
    @pytest.fixture
    def control(self) -> str:
        return (DEBIAN / "control").read_text()

    def test_the_source_is_the_distribution(self, control):
        assert f"Source: {SOURCE_PACKAGE}\n" in control

    def test_the_binary_is_the_import_package(self, control):
        """As the RPM is. Only the name on PyPI differs; see pyproject.toml."""
        assert f"Package: {BINARY_PACKAGE}\n" in control


def spec_floor(name: str) -> str:
    """The minimum version gtkpass.spec requires of a system library."""
    spec = SPEC.read_text()
    match = re.search(rf"^Requires:\s+{re.escape(name)}\s*>=\s*(\S+)", spec, re.M)
    assert match, f"gtkpass.spec no longer requires {name}"
    return match.group(1)


class TestTheDependencyFloorsAgree:
    """The same minimum, written twice, in two packages' spellings.

    Neither can be derived from the other -- Fedora calls the GTK4 runtime
    gtk4 and Debian calls the introspection data gir1.2-gtk-4.0 -- so what
    keeps them in step is this test. Raising one and forgetting the other is
    how a package installs on a system too old to run it.
    """

    @pytest.fixture
    def control(self) -> str:
        return (DEBIAN / "control").read_text()

    @pytest.mark.parametrize(
        "rpm_name,deb_name",
        [("gtk4", "gir1.2-gtk-4.0"), ("libadwaita", "gir1.2-adw-1")],
    )
    def test_the_floor_is_the_one_the_spec_names(self, control, rpm_name, deb_name):
        floor = spec_floor(rpm_name)
        assert f"{deb_name} (>= {floor})" in control, (
            f"gtkpass.spec requires {rpm_name} >= {floor}; "
            f"debian/control has to ask {deb_name} for the same"
        )


class TestWhatTheBuildDoesNotDo:
    @pytest.fixture
    def rules(self) -> str:
        return (DEBIAN / "rules").read_text()

    def test_the_suite_does_not_run_during_the_build(self, rules):
        """It needs a display, a session bus and a GPG key, none of which a
        build has. `make test` against the installed package is that gate, and
        CI runs it -- the same one the RPM gets.
        """
        assert re.search(r"^override_dh_auto_test:\s*$", rules, re.M), (
            "dh runs the suite unless the override is there and empty"
        )

    def test_it_ships_no_compiled_schema_cache(self, rules):
        """gschemas.compiled holds every application's schemas.

        libglib2.0's dpkg trigger recompiles the system cache when a package
        adds a schema, exactly as glib2's file trigger does on Fedora. Shipping
        one would overwrite the lot.
        """
        assert "gschemas.compiled" not in rules


class TestTheDesktopFilesTravel:
    """The four files named after the application id, as the spec installs them.

    A wheel carries none of them: they are the package's own work, and left out
    they are missing only once something is installed.
    """

    @pytest.mark.parametrize(
        "suffix", [".desktop", ".metainfo.xml", ".svg", ".gschema.xml"]
    )
    def test_the_rules_install_it(self, suffix):
        rules = (DEBIAN / "rules").read_text()
        assert suffix in rules, f"debian/rules installs no {suffix}"


needs_dpkg = pytest.mark.skipif(
    shutil.which("dpkg") is None or shutil.which("git") is None,
    reason="dpkg orders the versions and git supplies them",
)


def sorts_before(earlier: str, later: str) -> bool:
    """Whether dpkg would upgrade from ``earlier`` to ``later``."""
    return (
        subprocess.run(
            ["dpkg", "--compare-versions", earlier, "lt", later], check=False
        ).returncode
        == 0
    )


@needs_dpkg
class TestTheVersionSortsAgainstTheRelease:
    """Three states a checkout can be in, and one ordering they have to keep.

    The same three build-rpm.sh handles, in dpkg's spelling rather than rpm's.
    """

    @pytest.fixture
    def repository(self, tmp_path: Path) -> Path:
        """A checkout with one commit and no tags."""
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        for key, value in [("user.email", "t@example.com"), ("user.name", "T")]:
            subprocess.run(
                ["git", "-C", str(tmp_path), "config", key, value], check=True
            )
        (tmp_path / "a").write_text("a\n")
        subprocess.run(["git", "-C", str(tmp_path), "add", "a"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "one"], check=True)
        return tmp_path

    def version(self, repository: Path, target: str | None = None) -> tuple[str, str]:
        """The upstream and Debian versions the script derives, as it prints
        them: one line, two words.

        With a target, the version it produces for a build of that release.
        """
        result = subprocess.run(
            [str(DEB_VERSION), *([target] if target else [])],
            cwd=repository,
            capture_output=True,
            text=True,
            check=True,
        )
        upstream, debian = result.stdout.split()
        return upstream, debian

    def tag(self, repository: Path, name: str) -> None:
        subprocess.run(["git", "-C", str(repository), "tag", name], check=True)

    def dirty(self, repository: Path) -> None:
        (repository / "a").write_text("changed\n")

    def test_before_any_tag_it_sorts_before_the_release_to_come(self, repository):
        """`~` is the only thing that sorts before nothing at all, which is
        what a snapshot of an unreleased version has to do: the eventual
        0.1.0-1 upgrades over it.
        """
        upstream, version = self.version(repository)

        assert upstream == "0.1.0"
        assert sorts_before(version, "0.1.0-1"), version

    def test_on_a_tag_it_is_that_release(self, repository):
        self.tag(repository, "v0.1.0")

        upstream, version = self.version(repository)

        assert upstream == "0.1.0"
        assert version == "0.1.0-1"

    def test_a_dirty_tree_on_a_tag_sorts_after_it(self, repository):
        """Standing on a tag is not being it. Such a build is that release
        plus uncommitted changes, and says so rather than passing for it.
        """
        self.tag(repository, "v0.1.0")
        self.dirty(repository)

        _, version = self.version(repository)

        assert version != "0.1.0-1"
        assert sorts_before("0.1.0-1", version), version

    def test_the_target_is_in_the_version_when_one_is_named(self, repository):
        """Two targets, two packages, and both are ``Architecture: all``.

        dh_python3 derives the interpreter's dependencies from whatever apt
        hands the build, so the trixie package is not the Ubuntu one -- but
        their filenames are the same unless the version says which is which,
        and a release collects every artefact into one directory.
        """
        self.tag(repository, "v0.1.0")

        trixie = self.version(repository, "debian:trixie")[1]
        ubuntu = self.version(repository, "ubuntu:26.04")[1]

        assert trixie != ubuntu
        assert trixie == "0.1.0-1~debian.trixie", trixie
        # A colon is the epoch separator, so a version carrying one is not a
        # version at all -- and dpkg is what says so, rather than this test.
        assert ":" not in ubuntu, ubuntu

    def test_a_target_build_is_superseded_by_the_archive_it_is_not_from(
        self, repository
    ):
        """`~` sorts before nothing at all. These are built outside any
        archive, so a package from a real one has to win.
        """
        self.tag(repository, "v0.1.0")

        _, targeted = self.version(repository, "debian:trixie")

        assert sorts_before(targeted, "0.1.0-1"), targeted

    def test_the_target_does_not_disturb_the_ordering_it_carries(self, repository):
        """The commit still decides which of two snapshots is newer."""
        _, older = self.version(repository, "debian:trixie")
        (repository / "b").write_text("b\n")
        subprocess.run(["git", "-C", str(repository), "add", "b"], check=True)
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-qm", "two"], check=True
        )
        _, newer = self.version(repository, "debian:trixie")

        assert older != newer
        assert sorts_before(older, newer) or sorts_before(newer, older), (
            f"{older} and {newer} do not sort against each other at all"
        )

    def test_after_a_tag_it_sorts_after_that_release(self, repository):
        """A snapshot of work since a release, so an upgrade must not go
        backwards onto the release itself.
        """
        self.tag(repository, "v0.1.0")
        (repository / "b").write_text("b\n")
        subprocess.run(["git", "-C", str(repository), "add", "b"], check=True)
        subprocess.run(
            ["git", "-C", str(repository), "commit", "-qm", "two"], check=True
        )

        _, version = self.version(repository)

        assert sorts_before("0.1.0-1", version), version
        assert sorts_before(version, "0.2.0-1"), version
