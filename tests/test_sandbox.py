"""What the sandbox actually permits, read from /.flatpak-info.

Sync reaches a remote over ssh, and inside a Flatpak that needs permissions the
manifest deliberately does not request: the user grants them with `flatpak
override` if and when they want sync. So the application has to know whether it
has them, and say what to run when it does not.

The obvious probe is wrong. $SSH_AUTH_SOCK survives into a sandbox that was
denied --socket=ssh-auth: checked against flatpak 1.18.0, running the packaged
application with --nosocket=ssh-auth leaves the variable set to the host's
/run/user/1000/gcr/ssh while no such socket exists inside, so anything trusting
it concludes the agent is reachable and then hangs or fails at push time.

[Context] in /.flatpak-info does not have that problem. It is the effective
permission set, so it already accounts for overrides, and reading it is a file
read rather than a subprocess -- which matters because this is consulted while
deciding whether to make a button sensitive.
"""

from gtkpass import sandbox
from gtkpass.config import APP_ID

# As written by flatpak 1.18.0 for the packaged application, trimmed to the
# groups this module reads.
GRANTED = """\
[Application]
name=io.github.RonnyPfannschmidt.GTKPass

[Context]
shared=ipc;network;
sockets=fallback-x11;gpg-agent;inherit-wayland-socket;ssh-auth;wayland;
devices=dri;
filesystems=~/.password-store:create;
"""

# The same sandbox launched with --nosocket=ssh-auth --unshare=network, which is
# what a fresh install looks like once the manifest stops asking for them.
DENIED = """\
[Application]
name=io.github.RonnyPfannschmidt.GTKPass

[Context]
shared=ipc;
sockets=fallback-x11;gpg-agent;inherit-wayland-socket;wayland;
devices=dri;
filesystems=~/.password-store:create;
"""


def write_info(tmp_path, contents):
    path = tmp_path / "flatpak-info"
    path.write_text(contents)
    return path


class TestOutsideASandbox:
    """A checkout is not confined, so nothing is being withheld."""

    def test_it_knows_it_is_not_sandboxed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", tmp_path / "absent")

        assert not sandbox.is_sandboxed()

    def test_everything_is_permitted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", tmp_path / "absent")

        assert sandbox.has_socket("ssh-auth")
        assert sandbox.has_network()


class TestReadingTheGrantedPermissions:
    def test_a_granted_socket_is_seen(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", write_info(tmp_path, GRANTED))

        assert sandbox.has_socket("ssh-auth")

    def test_a_granted_share_is_seen(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", write_info(tmp_path, GRANTED))

        assert sandbox.has_network()

    def test_a_withheld_socket_is_seen(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", write_info(tmp_path, DENIED))

        assert not sandbox.has_socket("ssh-auth")

    def test_a_withheld_share_is_seen(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", write_info(tmp_path, DENIED))

        assert not sandbox.has_network()

    def test_the_gpg_agent_socket_is_unaffected(self, tmp_path, monkeypatch):
        """Denying ssh-auth must not be read as denying the other sockets."""
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", write_info(tmp_path, DENIED))

        assert sandbox.has_socket("gpg-agent")


class TestTheEnvironmentIsNotTrusted:
    """The regression this module exists for."""

    def test_a_leaked_ssh_auth_sock_does_not_count_as_permission(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", write_info(tmp_path, DENIED))
        monkeypatch.setenv("SSH_AUTH_SOCK", "/run/user/1000/gcr/ssh")

        assert not sandbox.has_socket("ssh-auth")


class TestAMalformedFileIsNotFatal:
    """A password manager must not fail to start over a diagnostic."""

    def test_an_unreadable_file_reports_nothing_granted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", write_info(tmp_path, "not ini {"))

        assert not sandbox.has_socket("ssh-auth")

    def test_a_file_without_a_context_group_reports_nothing_granted(
        self, tmp_path, monkeypatch
    ):
        info = write_info(tmp_path, "[Application]\nname=x\n")
        monkeypatch.setattr(sandbox, "FLATPAK_INFO", info)

        assert not sandbox.has_socket("ssh-auth")


class TestTheOverrideCommand:
    def test_it_names_this_application(self):
        assert APP_ID in sandbox.override_command()

    def test_it_is_not_hardcoded(self, monkeypatch):
        """One canonical identity: config.APP_ID, as everything else uses."""
        monkeypatch.setattr("gtkpass.sandbox.APP_ID", "org.example.Other")

        assert sandbox.override_command().endswith("org.example.Other")

    def test_it_asks_for_exactly_what_sync_needs(self):
        command = sandbox.override_command()

        assert "--socket=ssh-auth" in command
        assert "--share=network" in command

    def test_it_is_a_per_user_override(self):
        """--system would need root and would apply to every user on the box."""
        assert "--user" in sandbox.override_command()
