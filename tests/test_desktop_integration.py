"""The files the desktop needs, and the one identity running through them.

The D-Bus name, the desktop entry, the icon, the AppStream component and the
GSettings schema all have to be the same string. Nothing enforced that until
now because none of these files existed; packaging is the point at which a
mismatch stops being theoretical and starts being an application that installs
without an icon, or refuses to start at all.
"""

import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
from configparser import ConfigParser
from pathlib import Path

import pytest

from gtkpass.config import APP_ID, SCHEMA_ID, SCHEMA_PATH

DATA = Path(__file__).resolve().parent.parent / "data"

DESKTOP_FILE = DATA / f"{APP_ID}.desktop"
METAINFO_FILE = DATA / f"{APP_ID}.metainfo.xml"
ICON_FILE = DATA / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"
SCHEMA_FILE = DATA / f"{APP_ID}.gschema.xml"


class TestTheFilesExist:
    """Named after the application id, which is how the desktop finds them."""

    @pytest.mark.parametrize(
        "path",
        [DESKTOP_FILE, METAINFO_FILE, ICON_FILE, SCHEMA_FILE],
        ids=lambda p: p.name,
    )
    def test_file_is_present(self, path):
        assert path.is_file(), f"missing {path.relative_to(DATA.parent)}"


class TestTheDesktopEntry:
    @pytest.fixture
    def entry(self):
        parser = ConfigParser(interpolation=None, strict=False)
        parser.read(DESKTOP_FILE, encoding="utf-8")
        return parser["Desktop Entry"]

    def test_it_launches_the_installed_command(self, entry):
        """The console script pyproject declares, not a path into a checkout."""
        assert entry["Exec"].split()[0] == "gtkpass"

    def test_the_icon_is_the_application_id(self, entry):
        assert entry["Icon"] == APP_ID

    def test_it_declares_the_dbus_name(self, entry):
        """GTK matches this against the application id to route activation."""
        assert entry["StartupWMClass"] == APP_ID

    def test_it_validates(self):
        if shutil.which("desktop-file-validate") is None:
            pytest.skip("desktop-file-validate is not installed")

        result = subprocess.run(
            ["desktop-file-validate", str(DESKTOP_FILE)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr


class TestTheAppStreamComponent:
    @pytest.fixture
    def component(self):
        return ElementTree.parse(METAINFO_FILE).getroot()

    def test_the_id_is_the_application_id(self, component):
        assert component.findtext("id") == APP_ID

    def test_it_points_at_the_desktop_entry(self, component):
        """Without this the store entry and the installed app do not connect."""
        launchable = component.find("launchable[@type='desktop-id']")

        assert launchable is not None
        assert launchable.text == DESKTOP_FILE.name

    def test_the_licence_matches_the_project(self, component):
        """The repository is MPL-2.0; the metainfo must not claim otherwise."""
        assert component.findtext("project_license") == "MPL-2.0"

    def test_it_validates(self):
        if shutil.which("appstreamcli") is None:
            pytest.skip("appstreamcli is not installed")

        result = subprocess.run(
            ["appstreamcli", "validate", "--no-net", str(METAINFO_FILE)],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr


class TestTheSchemaAgrees:
    @pytest.fixture
    def schema(self):
        for element in ElementTree.parse(SCHEMA_FILE).getroot():
            if element.tag == "schema" and element.get("id") == SCHEMA_ID:
                return element
        pytest.fail(f"no schema with id {SCHEMA_ID} in {SCHEMA_FILE.name}")

    def test_the_path_is_derived_from_the_id(self, schema):
        assert schema.get("path") == SCHEMA_PATH


class TestTheFlatpakManifest:
    """Packaging must not drift from the identity either."""

    MANIFEST = Path(__file__).resolve().parent.parent / "build-aux" / f"{APP_ID}.yml"

    @pytest.fixture
    def manifest(self):
        if not self.MANIFEST.is_file():
            pytest.fail(f"missing {self.MANIFEST.name}")
        return self.MANIFEST.read_text()

    def test_the_manifest_is_named_after_the_application(self, manifest):
        assert f"app-id: {APP_ID}" in manifest

    def test_the_guard_is_opted_into(self, manifest):
        """A packaged build is the application actually being used.

        It does not go through run_app.sh, so without this the installed
        application refuses its own store and every backend fails to load.
        """
        assert "--env=GTKPASS_ALLOW_REAL_STORE=1" in manifest

    def test_the_password_store_is_reachable(self, manifest):
        assert "--filesystem=~/.password-store:create" in manifest

    def test_the_gpg_agent_socket_is_shared(self, manifest):
        """Decryption happens in the host agent; the sandbox never sees a key."""
        assert "--socket=gpg-agent" in manifest

    def test_the_ssh_agent_socket_is_not_requested(self, manifest):
        """Syncing needs it; opening a password store does not.

        Requested statically it would be held by every user whether or not
        their store has a remote, and Flathub asks for static permissions to be
        kept to a minimum. It is granted per user with `flatpak override`, and
        the application says so when a sync finds it missing.
        """
        granted = [
            line
            for line in manifest.splitlines()
            if line.strip().startswith("- --socket=ssh-auth")
        ]
        assert granted == [], f"ssh-auth is requested statically: {granted}"

    def test_network_access_is_not_requested(self, manifest):
        """Same reasoning: only reaching a git remote needs it."""
        granted = [
            line
            for line in manifest.splitlines()
            if line.strip().startswith("- --share=network")
        ]
        assert granted == [], f"network is requested statically: {granted}"

    def test_the_override_command_is_documented(self, manifest):
        """Whoever reads the manifest should find the way to turn sync on."""
        assert "flatpak override --user --socket=ssh-auth --share=network" in manifest

    def test_the_ssh_files_are_not_requested(self, manifest):
        """An ssh remote needs them; opening a store does not.

        And ~/.ssh/config is an inventory of the machines someone reaches, so
        it is the user's call rather than the manifest's.
        """
        granted = [
            line
            for line in manifest.splitlines()
            if line.strip().startswith("- --filesystem=~/.ssh")
        ]
        assert granted == [], f"an ~/.ssh grant is requested statically: {granted}"

    def test_the_ssh_file_override_is_documented(self, manifest):
        """The failure it fixes reads as DNS, so the cure has to be findable."""
        assert "--filesystem=~/.ssh/config:ro" in manifest
        assert "--filesystem=~/.ssh/known_hosts:ro" in manifest

    def test_the_whole_ssh_directory_is_never_granted(self, manifest):
        """It mixes the private keys in with the two files actually wanted."""
        assert "- --filesystem=~/.ssh:ro" not in manifest
        assert "- --filesystem=~/.ssh\n" not in manifest

    def test_the_git_configuration_directory_is_readable(self, manifest):
        """Without it git has no author identity and refuses to commit.

        flatpak points XDG_CONFIG_HOME at the app's own directory, so the
        host's ~/.config/git is not what git reads unless it is mounted, and a
        local commit is not an opt-in feature -- it is on for every git-backed
        store.
        """
        assert "- --filesystem=xdg-config/git:ro" in manifest

    def test_the_git_configuration_grant_is_read_only(self, manifest):
        """git never writes it, and the application has no business doing so."""
        granted = [
            line.strip()
            for line in manifest.splitlines()
            if line.strip().startswith("- --filesystem=xdg-config/git")
        ]
        assert granted == ["- --filesystem=xdg-config/git:ro"]

    def test_git_is_still_bundled(self, manifest):
        """Local commits need git regardless of whether a remote exists."""
        assert "name: git" in manifest
