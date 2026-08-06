# GTKPass in a Flatpak

What a sandboxed password manager needs in order to reach GPG, SSH and git, why
each permission is granted, and what was deliberately refused.

Everything below about the runtime was checked against `org.gnome.Platform//50`
as installed, not assumed.

## Build it

```bash
make flatpak       # build and install for the current user
make flatpak-run
make flatpak-lint  # the checks Flathub runs on submission
```

The first build downloads `org.gnome.Sdk//50`, which is a couple of gigabytes.

## What the runtime already provides

`org.gnome.Platform//50` ships more than you might expect, which keeps the
manifest short:

| Tool | In the runtime? |
| --- | --- |
| `gpg`, `gpg-agent`, `gpgconf`, `gpgsm`, `gpgv` | yes |
| `pinentry`, `pinentry-gnome3` | yes |
| `ssh`, `ssh-add`, `ssh-agent`, `ssh-keygen`, `ssh-keyscan` | yes |
| `python3` (3.13), PyGObject, pycairo | yes |
| `blueprint-compiler` | yes |
| `libsecret`, `libgpgme` | yes |
| **`git`** | **no** |
| **`libgit2`, `libssh2`** | **no** |
| **`pass`** | **no** |

So GPG and SSH need permissions but no bundling. Git needs both.

## GPG

Two separate things are required, and conflating them is the usual mistake.

**The agent, for private-key operations.** `--socket=gpg-agent` exposes the
host's agent socket (whatever `gpgconf --list-dir agent-socket` reports). The
private keys stay on the host, the host agent does the decryption, and the
passphrase prompt is the host's own pinentry. Nothing secret crosses into the
sandbox.

This needs a running agent on the host. Under systemd socket activation there
normally is one; if not, `gpg` in the sandbox cannot start it and will fail to
connect.

**The public keyring, for resolving recipients.** The agent does not answer
"which key is `alice@example.com`?" — `gpg` reads that from `GNUPGHOME`, which
inside the sandbox points at an inaccessible `~/.gnupg`. Granting the specific
files is enough, read-only:

```
--filesystem=~/.gnupg/pubring.kbx:ro
--filesystem=~/.gnupg/public-keys.d/pubring.db:ro   # gpg 2.4 and later
--filesystem=~/.gnupg/common.conf:ro
```

This is what [Identities](https://flathub.org/apps/one.k8ie.Identities), the
closest existing application, does. The whole of `~/.gnupg` is deliberately not
granted: it holds `private-keys-v1.d`, which is exactly what the agent socket
exists to keep out of reach.

Read-only works for GTKPass because `DirectBackend._encrypt_to_file` encrypts
with `always_trust=True`, so `gpg` never has to write the trust database. An
application that manages keys cannot get away with this;
[Kleopatra](https://flathub.org/apps/org.kde.kleopatra) takes
`--filesystem=~/.gnupg:create` plus `--filesystem=xdg-run/gnupg:ro` instead.

## SSH

Only relevant once something talks to a remote, which today nothing does.

`--socket=ssh-auth` exposes `$SSH_AUTH_SOCK`, so an agent on the host does the
authentication and the private key never enters the sandbox — the same shape as
the GPG arrangement. `gitg` is the reference here.

Host verification needs `known_hosts`, which means `--filesystem=~/.ssh:ro`. It
grants the private keys too; there is no narrower option, since `~/.ssh` mixes
both. Prefer relying on the agent.

Keys not loaded into an agent cannot be used without that filesystem grant.

## Git

`git` is not in the runtime, so there are three ways to get it, in descending
order of preference:

1. **Bundle libgit2** and drive it from Python (`pygit2`), which is what `gitg`
   does. No subprocess, no PATH, and the library is small. `pygit2` needs
   `libgit2` built as a module first.
2. **Bundle the `git` binary** as a module. Straightforward — its dependencies
   (curl, expat, zlib, openssl) are all in the runtime — but it is a large
   module to maintain for what a password store actually needs, which is
   `add`, `commit`, `pull` and `push`.
3. **`flatpak-spawn --host git`**, which needs
   `--talk-name=org.freedesktop.Flatpak`. Do not. See below.

Either way `--share=network` is required, and ssh remotes additionally need the
SSH permissions above.

## What is refused, and why

**`--talk-name=org.freedesktop.Flatpak`.** This is the one worth being explicit
about. It permits `flatpak-spawn --host`, which runs arbitrary commands on the
host outside the sandbox — it is not a narrow escape hatch, it is the end of
the sandbox. `PassBackend` is written to use exactly this (`_is_flatpak()`
switches it to `flatpak-spawn --host pass`), so **the Pass backend does not
work in the packaged application**, by choice.

That costs little: `DirectBackend` reads and writes the same passwordstore
format natively, using the `gpg` already in the runtime. The Pass backend
remains useful outside the sandbox, where `pass` is on `PATH`.

**`--share=network`.** Nothing in the application opens a socket. It becomes
necessary the day git sync exists, and not before.

**`--filesystem=home` or `--filesystem=host`.** A password manager asking for
the whole home directory is exactly the thing a sandbox is meant to prevent.
`~/.password-store` is granted instead, and a store elsewhere is an override:

```bash
flatpak override --user --filesystem=/path/to/store io.github.RonnyPfannschmidt.GTKPass
```

## The Secret Service backend

`--talk-name=org.freedesktop.secrets` is granted, and `libsecret` is in the
runtime — but the backend uses the `secretstorage` Python package, which
depends on `cryptography`. That is a Rust build needing an SDK extension, for
one optional backend, so it is not bundled yet.

The consequence is visible rather than silent: `secretservice.py` imports it in
a `try`, so the backend reports itself unavailable and the sidebar says so.

## The safety guard and packaged builds

`src/gtkpass/safety.py` refuses the real store and the keyring unless
`GTKPASS_ALLOW_REAL_STORE` is set. In a checkout only `run_app.sh` sets it; a
packaged application does not go through that script, so the manifest sets it
with `--env=GTKPASS_ALLOW_REAL_STORE=1`.

Without that line the installed application refuses its own password store and
every backend fails to load. A test asserts the manifest contains it.

The guard protects developers from their own scratch code. It is not what
protects the user's data in a packaged build — the sandbox is.

## Still missing before this could go to Flathub

- A stable release tag; the manifest builds from the working directory
  (`type: dir`) and pins the version with `SETUPTOOLS_SCM_PRETEND_VERSION`. A
  submission needs a `type: git` source at a tag with a commit hash.
- Screenshots in the AppStream metainfo. Flathub requires at least one, and it
  must be reachable over the network at review time.
- A real icon. The one in `data/icons` is a placeholder, and Flathub reviews
  icons for quality.
- `secretstorage`, if the Secret Service backend is meant to work.
