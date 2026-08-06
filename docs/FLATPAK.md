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
| **`pass`**, **`tree`** | **no** |

So GPG and SSH need permissions but no bundling. `pass`, `tree` and `git` are
bundled as modules; see below.

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

Both spellings of the keyring are granted because both are in the field.
GnuPG 2.4 and later default to **keyboxd**, where `common.conf` says
`use-keyboxd`, the keys live in `public-keys.d/pubring.db`, and `gpg` does not
read that file directly at all — it asks the keyboxd daemon over a socket.
Older setups keep a plain `pubring.kbx` that `gpg` reads itself. Flatpak skips
a grant whose file does not exist, so listing both costs nothing.

The keyboxd case works because `--socket=gpg-agent` turns out to expose the
whole of `/run/user/$UID/gnupg`, `S.keyboxd` included, not just `S.gpg-agent`
as its name and the documentation suggest. Verified in the built sandbox:
`gpg --list-keys` returns the host's keys, served by the host's keyboxd.

One consequence worth knowing when testing: you cannot point `GNUPGHOME` at a
*different* keyring inside the sandbox. `gpg` then wants its own agent, and
tries to create a socket under `/run/user/$UID/gnupg`, which is bound read-only
from the host. It hangs rather than failing. Test against the real home, or
outside the sandbox.

Read-only works for GTKPass because `DirectBackend._encrypt_to_file` encrypts
with `always_trust=True`, so `gpg` never has to write the trust database. An
application that manages keys cannot get away with this;
[Kleopatra](https://flathub.org/apps/org.kde.kleopatra) takes
`--filesystem=~/.gnupg:create` plus `--filesystem=xdg-run/gnupg:ro` instead.

## SSH

Relevant because the bundled `pass` can drive `git` against a remote, though
nothing in the interface asks it to yet.

`--socket=ssh-auth` exposes `$SSH_AUTH_SOCK`, so an agent on the host does the
authentication and the private key never enters the sandbox — the same shape as
the GPG arrangement. `gitg` is the reference here.

Host verification needs `known_hosts`, which means `--filesystem=~/.ssh:ro`. It
grants the private keys too; there is no narrower option, since `~/.ssh` mixes
both. Prefer relying on the agent.

Keys not loaded into an agent cannot be used without that filesystem grant.

## Git

`git` is not in the runtime. Three ways to get it, in descending order of
preference:

1. **Bundle the `git` binary** as a module. Its dependencies (curl, expat,
   zlib, openssl) are all in the runtime, so it is a plain autotools build.
   This is what the manifest does, because `pass` drives `git` as a command and
   nothing else would satisfy it.
2. **Bundle libgit2** and drive it from Python (`pygit2`), which is what `gitg`
   does. Smaller and subprocess-free, and the right choice if GTKPass ever
   grows its own git support rather than delegating to `pass`.
3. **`flatpak-spawn --host git`**, which needs
   `--talk-name=org.freedesktop.Flatpak`. Do not. See below.

Either way `--share=network` is required to reach a remote, and ssh remotes
additionally need the SSH permissions above.

## Bundling pass, rather than borrowing the host's

The Pass backend needs the `pass` executable, which is not in the runtime.
There are two ways to get one, and they are not close in cost.

`flatpak-spawn --host pass` asks the host to run it. That needs
`--talk-name=org.freedesktop.Flatpak`, which is not a narrow hole for one
command: it permits running *any* command on the host, outside the sandbox. For
a password manager that is the end of the sandbox, and it is refused here.

So `pass` is bundled and runs inside. It brings two dependencies of its own:

- **`tree`**, because `pass ls` shells out to it. Without it, listing — the
  backend's most basic operation — fails.
- **`git`**, because `pass` commits to the store's repository by itself
  whenever one is present. Without it, every write to a git-backed store fails.

Both are small. `pass` itself is a bash script, and it uses the `gpg` and `ssh`
already in the runtime, so nothing crosses the sandbox boundary except through
the agent sockets.

This is what makes `--socket=ssh-auth` and `--share=network` worth granting:
`pass git push` reaches a remote over ssh, authenticated by the host's agent,
with the private key never entering the sandbox. The interface has no sync
button yet, so nothing triggers that today.

## What is refused, and why

**`--talk-name=org.freedesktop.Flatpak`**, as above.

**`--filesystem=~/.ssh:ro`.** It would provide `known_hosts`, but hands over
every private key in the same grant; `~/.ssh` mixes both and there is no
narrower spelling. The agent socket authenticates without them.

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

## Why everything is built from source

There is no way to install a prebuilt `git` or `openssh` into a Flatpak and
share it between applications. The mechanism that would do it exists —
**runtime extensions**, declared as `[Extension ...]` points in a runtime's
metadata and mounted into the sandbox at a fixed directory — and it is how
Mesa, VAAPI, GStreamer codecs, the icon themes and the whole
`org.freedesktop.Sdk.Extension.*` family of toolchains are distributed once and
used by many applications.

Nobody publishes one for git or ssh. Flathub carries extensions for `golang`,
`llvm`, `dotnet`, `node`, `haskell`, `mono`, `mingw-w64` and similar; a search
for a git or openssh extension returns nothing. Creating one means publishing
and maintaining a runtime extension of your own, which is only worth it with
several consumers.

`org.gnome.Sdk` *does* ship git, and its binaries do link only against
libraries the Platform has (checked: libz, libpcre2, libcurl, libgcc_s, libc).
Copying them into the application at build time would work today. It is still
the wrong trade: the SDK is a build environment, not a redistribution channel,
so nothing promises the next one stays Platform-compatible, and the failure
would appear at runtime on a user's machine rather than during the build. The
manifest would also stop describing what it ships — no version, no hash, and
nothing for Flathub's update checker to follow.

Building from source costs build time once, is cached by flatpak-builder
afterwards, and states exactly which git is in the bundle.

## Still missing before this could go to Flathub

- A stable release tag; the manifest builds from the working directory
  (`type: dir`) and pins the version with `SETUPTOOLS_SCM_PRETEND_VERSION`. A
  submission needs a `type: git` source at a tag with a commit hash.
- Screenshots in the AppStream metainfo. Flathub requires at least one, and it
  must be reachable over the network at review time.
- A real icon. The one in `data/icons` is a placeholder, and Flathub reviews
  icons for quality.
- `secretstorage`, if the Secret Service backend is meant to work.
