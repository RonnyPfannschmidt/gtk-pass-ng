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

It also means *how* the host unwraps the key is none of the sandbox's business.
A smartcard via `scdaemon`, or a TPM-bound key via `tpm2daemon`, works through
this same grant and needs **no** additional permission — no `--device=`, no
`/dev/tpmrm0`. Verified in the built sandbox: it has neither `tpm2daemon` nor any
`/dev/tpm*`, and reaches the agent regardless, because the daemon doing the work
runs on the host. See [TRUST-MODEL.md](TRUST-MODEL.md).

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

## SSH, and why it is not in the manifest

The sync action pulls and pushes a store that has a git remote. Over ssh that
needs `--socket=ssh-auth`, which exposes `$SSH_AUTH_SOCK` so an agent on the
host does the authentication and the private key never enters the sandbox — the
same shape as the GPG arrangement. It also needs `--share=network`.

**Neither is requested.** Most stores have no remote, and a password manager
holding network access and an agent socket on the chance that one does is
exactly the request that deserves scrutiny. They are opt-in, per user:

```bash
flatpak override --user --socket=ssh-auth --share=network io.github.RonnyPfannschmidt.GTKPass
```

`flatpak override` is the mechanism for this, and its man page says so outright:
it exists to *"grant a sandboxed application more or less resources than it
requested"*. Flatseal does the same thing graphically. The bundled `git` still
commits locally, which needs neither permission.

`src/gtkpass/sandbox.py` checks whether they have been granted, and the sync
action shows that exact command, copyable, when they have not — raised before
any git process starts, so nothing blocks on a socket that was never mounted.

That command is necessary but not sufficient for an ssh remote: two files out
of `~/.ssh` are needed as well, and are granted separately. See
[`~/.ssh/config` and `known_hosts`](#sshconfig-and-known_hosts) below.

### An extension cannot carry the permission instead

Worth writing down because it looks like it should. Checked against
`flatpak-metadata(5)` and flatpak 1.18.0:

- `[Extension NAME]` accepts only `directory`, `version`/`versions`,
  `add-ld-path`, `merge-dirs`, `download-if`/`enable-if`, `autodelete`,
  `no-autodownload` and `subdirectories` — all about *what content mounts
  where*.
- `[ExtensionOf]`, on the extension side, accepts only `ref`, `runtime`,
  `priority` and `tag`.
- Neither has a `[Context]` group.

An extension is content mounted into a sandbox whose `[Context]` was fixed at
`flatpak build-finish`; it never widens it. Conditional permissions
(`--share-if=`, flatpak 1.17 and later) do exist, but cover only `network` and
`ipc` and condition on system capabilities such as `has-wayland`, not on
anything the user chose. So there is no packaging trick here, only the override.

### `$SSH_AUTH_SOCK` is not a usable probe

The obvious check is wrong, and wrong in the direction that hangs. Running the
packaged application with `--nosocket=ssh-auth` leaves `SSH_AUTH_SOCK` set — to
the host's `/run/user/$UID/gcr/ssh`, leaked through the environment — while
`/run/flatpak/` contains no `ssh-auth` at all and `ssh-add -l` exits 2. Code
trusting the variable concludes the agent is reachable and finds out otherwise
at push time.

`[Context]` in `/.flatpak-info` has neither problem. `flatpak-metadata(5)`
describes it as the effective configuration, so it already accounts for every
override, and reading it is a file read rather than a subprocess — which matters
because it decides whether a button is sensitive.

### `~/.ssh/config` and `known_hosts`

The agent socket and the network are not enough. An ssh remote needs two files
out of `~/.ssh` as well, and without them the failure does not look like a
permissions problem at all — which is the reason this section exists. Both
symptoms below were reproduced against flatpak 1.18.0 with `--socket=ssh-auth
--share=network` already granted:

| Missing | What ssh says |
| --- | --- |
| `~/.ssh/config` | `ssh: Could not resolve hostname gh: Name or service not known` |
| `~/.ssh/known_hosts` | `No ED25519 host key is known for github.com and you have requested strict checking` |

`config` is where `Host` aliases are defined, so a remote written as
`git@gh:me/store.git` is not a hostname at all until that file has been read. A
sandbox without it hands the alias to the resolver verbatim and gets a DNS
error for a cause that is a missing permission.

`known_hosts` is the other half. `GitStore._build_env` pins
`StrictHostKeyChecking=yes` — not `accept-new`, which would take whatever key
answers the first connection, precisely when somebody in the way cannot be
detected — so every ssh remote stops at host key verification without it. Worse
than stopping: the obvious remedy is a trap. `ssh-keyscan host >> ~/.ssh/known_hosts`
run on the host changes a file the sandbox cannot see, so it appears to do
nothing.

**Not `--filesystem=~/.ssh:ro`.** That grants every private key in the same
breath, since `~/.ssh` mixes both and there is no narrower spelling of the
directory. There does not need to be — `--filesystem` takes a *file* path:

```bash
flatpak override --user --filesystem=~/.ssh/config:ro \
    --filesystem=~/.ssh/known_hosts:ro io.github.RonnyPfannschmidt.GTKPass
```

Verified from inside the resulting sandbox: `ls ~/.ssh` shows exactly those two
files, and nothing else. No `id_ed25519`, no `id_rsa`. Read-only because ssh
has no reason to write either — in batch mode with strict checking it never
appends to `known_hosts`, and it never writes `config` at all.

These are opt-in for the same reason the socket is, and one more: an https
remote needs neither, and `~/.ssh/config` is an inventory of the machines
someone reaches — hostnames, ports, usernames, jump hosts. It carries no
secret, but it is not nothing, and whether GTKPass gets to read it is the
user's call rather than the manifest's.

`GitStore.explain()` recognises both failures, checks `sandbox.has_filesystem()`
to confirm the grant is actually the cause, and puts the command above on
screen. Outside a sandbox, or once the file is mounted, an unresolved name is
DNS or a typo and the error is passed through unchanged — a permissions story
told over a real DNS failure sends the user to fix something that is not broken.

#### `IdentitiesOnly yes` needs the `.pub` too

The one case the two files do not cover, and it fails in a way that looks like
the agent is broken. A `Host` block combining `IdentitiesOnly yes` with
`IdentityFile ~/.ssh/id_x` restricts ssh to that one key, and ssh has to read
either `id_x` or `id_x.pub` to work out *which* agent key that is. Inside the
sandbox neither exists, so:

```
no such identity: /home/you/.ssh/id_x: No such file or directory
…: Permission denied (publickey).
```

Granting the **public** half fixes it — ssh then resolves the explicit identity
onto the agent key (`Will attempt key: …/id_x ED25519 … explicit agent`):

```bash
flatpak override --user --filesystem=~/.ssh/id_x.pub:ro io.github.RonnyPfannschmidt.GTKPass
```

A `.pub` file is public by definition, so this gives away nothing. There is no
glob spelling in `--filesystem`, so it is one grant per key, and GTKPass does
not suggest it automatically: guessing which key a `Host` block meant would
mean parsing `~/.ssh/config`, which is the file it cannot read.

Two smaller ones with no remedy worth automating: an `Include` directive points
at files that are not mounted, and a `UserKnownHostsFile` pointing somewhere
other than the default is not covered by the grant above. A `ControlPath` under
`~/.ssh` is not writable inside the sandbox, but ssh warns and carries on
without multiplexing.

Keys not loaded into an agent cannot be used at all.

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
additionally need the SSH permissions above — neither of which the manifest
requests, so reaching a remote is something the user opts into.

Local commits need none of that. `DirectBackend` commits every write to a
git-backed store through the bundled `git`, and `pass` does its own committing,
so a store stays consistent with its history whether or not sync is ever
enabled.

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

The sync button in the header bar is what drives this: it pulls and pushes,
reaching a remote over ssh, authenticated by the host's agent, with the private
key never entering the sandbox. That is also the only thing that needs
`--socket=ssh-auth` and `--share=network`, which is why the manifest leaves both
to a `flatpak override` rather than requesting them for everyone.

## What is refused, and why

**`--talk-name=org.freedesktop.Flatpak`**, as above.

**`--filesystem=~/.ssh:ro`.** It would provide `known_hosts`, but hands over
every private key in the same grant; `~/.ssh` mixes both and there is no
narrower spelling. The agent, once granted, authenticates without them.

**`--filesystem=home` or `--filesystem=host`.** A password manager asking for
the whole home directory is exactly the thing a sandbox is meant to prevent.
`~/.password-store` is granted instead, and a store elsewhere is an override:

```bash
flatpak override --user --filesystem=/path/to/store io.github.RonnyPfannschmidt.GTKPass
```

## The document portal

GTKPass does not use it. There is no file chooser and nothing is exported
through a portal: the store path comes from GSettings and the files are opened
directly, which is what `--filesystem=~/.password-store` is for.

Flatpak mounts it anyway. `flatpak run` binds
`$XDG_RUNTIME_DIR/doc/by-app/$FLATPAK_ID` into every sandbox unconditionally —
even a bare `flatpak run --command=sh org.gnome.Platform//50`, which has no
filesystem permissions at all, fails when that path is missing. So it is not
something the application asks for and not something it can decline.

Two consequences, and neither is hypothetical:

- Every document any application has exported through the portal is visible
  inside a password manager, for no purpose.
- If the portal is unavailable — its service running but its FUSE mount
  absent, as happened here — **the application does not start**, with
  `bwrap: Can't find source path .../doc/by-app/...` and nothing else.

The only lever is `flatpak run --no-documents-portal`, which works; `make
flatpak-run` passes it. It cannot be baked in:

- `flatpak build-finish` has no such option, so it cannot go in `finish-args`.
- `flatpak override` does not accept it either.
- `X-Flatpak-RunOptions=--no-documents-portal` in the desktop file does not
  work. Tested against flatpak 1.18.0: the key reaches the installed
  application, is stripped during export, and the exported `Exec` is unchanged
  — a plain `flatpak run` still mounts the portal.

Anyone launching GTKPass from a desktop menu therefore gets the portal
regardless. Changing that needs a flatpak feature that does not exist yet.

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

It is worth being clear about what that mechanism would and would not buy,
because "make it an extension" is the obvious answer to more than one problem
here and is only the answer to one of them. An extension can ship a payload
optionally and share it between applications. It **cannot** carry a permission:
neither `[Extension NAME]` nor `[ExtensionOf]` has a `[Context]` group, so an
extension is content mounted into a sandbox whose permissions were already
fixed. Packaging git or ssh as an extension would not have moved
`--socket=ssh-auth` out of this application's own permission set; see the SSH
section above for what does.

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

The submission process itself, and the permission exceptions it needs, are in
[FLATHUB.md](FLATHUB.md).

- A stable release tag; the manifest builds from the working directory
  (`type: dir`) and pins the version with `SETUPTOOLS_SCM_PRETEND_VERSION`. A
  submission needs a `type: git` source at a tag with a commit hash.
- Screenshots in the AppStream metainfo. Flathub requires at least one, and it
  must be reachable over the network at review time.
- A real icon. The one in `data/icons` is a placeholder, and Flathub reviews
  icons for quality.
- `secretstorage`, if the Secret Service backend is meant to work.
