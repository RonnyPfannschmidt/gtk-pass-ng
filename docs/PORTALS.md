# There is no GPG portal, and nobody is writing one

Research note, current as of 2026-08-07. The question was whether an
xdg-desktop-portal interface for GPG or SSH exists or is coming, because if one
were, `--socket=gpg-agent` in the Flatpak manifest would be a stopgap with an
end date rather than the permanent arrangement it actually is.

It is the permanent arrangement. Every finding below was read off the upstream
trackers directly, not inferred.

## The three proposals, all open, none implemented

| issue | opened | last activity | state |
| --- | --- | --- | --- |
| [#284](https://github.com/flatpak/xdg-desktop-portal/issues/284) Add a portal to manage ssh keys | 2019-01-01 | 2026-02-25 | open, 11 comments, no PR |
| [#178](https://github.com/flatpak/xdg-desktop-portal/issues/178) Portal for GPG encryption/decryption | 2018-04-03 | 2023-10-20 | open, 7 comments, no PR |
| [#500](https://github.com/flatpak/xdg-desktop-portal/issues/500) Add a portal for GnuPG pinentry | 2020-06-17 | 2021-10-26 | open, **zero comments, ever** |

Searching every pull request ever opened against xdg-desktop-portal for `ssh`,
`gpg`, `gnupg` or `pinentry` returns four results, none of them related — a
document-portal `flock` change, a notification spec, a file chooser change, and
a release checklist. There has never been an attempt at an implementation.

Nothing in the [New Portals discussion
category](https://github.com/flatpak/xdg-desktop-portal/discussions/categories/new-portals)
touches either subject either, and that category is busy: sixty-odd threads with
2026 activity, covering audio, clipboard, alarms, coredumps, mDNS and a portal
to escape the sandbox. Nobody has revived these.

### Why they stalled

Not neglect — disagreement about what the interface should be.

On #284, Matthias Clasen's first response was that key access is the wrong
altitude, and the portal should offer *"open an ssh tunnel to ..."* instead.
bilelmoussaoui's actual need was picking a key for commit signing, which that
does not cover. The two use cases were never reconciled and the thread went
quiet for four years.

On #178, TingPing stated the requirement plainly in 2019: *"an application that
relies on this needs to write out its API needs (and ideally make an
implementation)"*. In seven years nobody has written either.

#500 is the interesting one for a password manager, because it is the only
proposal aimed at the part that genuinely cannot be bundled. `pinentry` has one
implementation per desktop, each dragging in Qt or GCR or gtk-2, and the
Freedesktop SDK ships none of them, so a runtime is left with the ncurses
tty backend and no way to prompt. That is exactly the shape of problem portals
exist to solve, and it received no reply in six years.

### The counter-argument that keeps winning

Raised by nanonyme on both threads: `ssh-agent` and `gpg-agent` already keep
secret material on the host, already gather user consent, and access is already
revocable per-app with Flatseal. A portal would re-implement a boundary that
exists.

The rebuttal is better, and is the only movement on any of this in three years —
jslarraz, 2026-02-25 on #284: agent consent is granted **per key-add, not per
use**. Once `ssh-add` has unlocked a key, every application holding the socket
can use it without limit. `ssh-add -c` prompts on every use instead, which is
correct and unusable. A portal could gate first use *per application* with a
cheap accept/deny, having already unlocked the key once.

GeorgesStavracas, maintainer, 2023-10-23, on whether the socket permission makes
the portal unnecessary: *"my general assumption is that static permissions
should be deprecated as much as possible, so without further context I'd say
this is still necessary."*

Correct in principle. Still nobody's code.

## What ships instead

Static sandbox holes, both long since merged and both what every app in this
space actually uses:

- `--socket=ssh-auth` — [flatpak#1438](https://github.com/flatpak/flatpak/issues/1438), closed 2018-07-11
- `--socket=gpg-agent` — [flatpak#4958](https://github.com/flatpak/flatpak/pull/4958), merged 2022-08-16, released in Flatpak 1.14.0

The [Secret
portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Secret.html)
is unrelated despite the name. It hands an application a per-app master secret
for encrypting its own data inside the sandbox. It is not a route to the user's
keys, and it is not a password manager interface.

The one live credential-adjacent effort is the [Credentials Portal
spec](https://github.com/flatpak/xdg-desktop-portal/discussions/1863), opened
2025-11-14 and still active as of 2026-06-27, built on
[credentialsd](https://github.com/linux-credentials/credentialsd). It is
WebAuthn and passkeys — `CreateCredential`, `GetCredential`, JSON blobs from the
WebAuthn spec. There is no path from it to GPG or SSH. The older [password
portal discussion](https://github.com/flatpak/xdg-desktop-portal/discussions/2061)
(2019) is about cross-application autofill and stalled on the same question of
whether libsecret or the portal is the right abstraction layer.

## What this means for GTKPass

`--socket=gpg-agent` is what there is. Plan for it to stay.

It carries a cost that the manifest comment at
[`build-aux/io.github.RonnyPfannschmidt.GTKPass.yml`](../build-aux/io.github.RonnyPfannschmidt.GTKPass.yml)
currently understates. In April 2026 Flatpak published [an
advisory](https://github.com/flatpak/flatpak/issues/6564) stating that the
socket is an **arbitrary code execution sandbox escape**, and closed it as not
planned — working as intended, published only because the consequence is not
obvious from the permission's name.

The mechanism: `gpg-agent` accepts environment variables from its client,
including `DBUS_SESSION_BUS_ADDRESS`, and forwards them to the host's pinentry.
A compromised application sets crafted values and gets code execution on the
host. Beyond that it can enumerate secret keys, generate new keypairs, mark keys
trusted, and raise arbitrary passphrase prompts for phishing.

So "no private key ever enters the sandbox" is true and beside the point. The
socket does not need to leak the key to be a full escape. Flathub's review
diagnoses `--socket=gpg-agent` as potentially unsafe, so this will come up at
submission whether or not the wording changes first.

### The one hardening avenue worth trying

The advisory names a mitigation Flatpak considered and rejected: point the
socket at `S.gpg-agent.extra` instead, which permits **signing and decryption
only**. They rejected it globally because some apps using `--socket=gpg-agent`
generate keypairs and would regress.

GTKPass does not generate keypairs. Signing and decryption is the entire
requirement, so the objection that killed it upstream does not apply here.

Unverified, and the reason this is a note rather than a change:

- The bind would have to be `--filesystem=xdg-run/gnupg/S.gpg-agent.extra`
  rather than `--socket=gpg-agent`, and `gpg` inside the sandbox has to be
  pointed at it — GnuPG's socket-redirect file in `$GNUPGHOME` is the documented
  mechanism, but it has not been tried here.
- [flatpak#5095](https://github.com/flatpak/flatpak/issues/5095) reports that
  combining `--socket=gpg-agent` with `--filesystem=xdg-run/gnupg` crashes
  Flatpak with SIGSEGV, so it has to be one or the other, never both.
- pinentry would prepend *"Note: Request from a remote site."* to every prompt,
  because the extra socket is designed for ssh forwarding. That is a UI
  regression to weigh against the hardening.

### Follow-up

- [ ] Reword the `--socket=gpg-agent` comment in the manifest so it does not
      read as a security argument. Cite the advisory.
- [ ] Prototype the `S.gpg-agent.extra` route and measure what breaks.
- [ ] Say plainly in [FLATHUB.md](FLATHUB.md) why the permission is required,
      before a reviewer asks.
- [ ] Re-check #284, #178 and #500 before any future Flathub submission. Cheap,
      and the position above is only as current as its date.

## References

Portals:

- [xdg-desktop-portal#284 — Add a portal to manage ssh keys](https://github.com/flatpak/xdg-desktop-portal/issues/284)
- [xdg-desktop-portal#178 — Portal for GPG encryption/decryption](https://github.com/flatpak/xdg-desktop-portal/issues/178)
- [xdg-desktop-portal#500 — Add a portal for GnuPG pinentry](https://github.com/flatpak/xdg-desktop-portal/issues/500)
- [xdg-desktop-portal#1863 — Credentials Portal Spec](https://github.com/flatpak/xdg-desktop-portal/discussions/1863)
- [xdg-desktop-portal#2061 — Add password portal](https://github.com/flatpak/xdg-desktop-portal/discussions/2061)
- [New Portals discussion category](https://github.com/flatpak/xdg-desktop-portal/discussions/categories/new-portals)
- [Secret portal documentation](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Secret.html)

Flatpak:

- [flatpak#6564 — Informational: `--socket=gpg-agent` is a sandbox escape](https://github.com/flatpak/flatpak/issues/6564)
- [flatpak#1438 — ssh-agent socket](https://github.com/flatpak/flatpak/issues/1438)
- [flatpak#4958 — add `--socket=gpg-agent`](https://github.com/flatpak/flatpak/pull/4958)
- [flatpak#5095 — `--socket=gpg-agent` plus `--filesystem=xdg-run/gnupg` crashes](https://github.com/flatpak/flatpak/issues/5095)

Related here:

- [TRUST-MODEL.md](TRUST-MODEL.md) — what decryption costs and why the agent is on the host
- [FLATPAK.md](FLATPAK.md) — the manifest and how the sandbox is put together
- [FLATHUB.md](FLATHUB.md) — what submission requires
