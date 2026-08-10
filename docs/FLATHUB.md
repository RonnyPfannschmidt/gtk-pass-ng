# Submitting GTKPass to Flathub

The Flatpak in [FLATPAK.md](FLATPAK.md) builds and installs locally. Publishing
it is a separate exercise with its own rules, and this one needs permissions
Flathub flags by default. What follows is the process, what GTKPass already
satisfies, and what is still missing.

Checked against the linter as of August 2026, not from memory: `make
flatpak-lint` runs the same checks Flathub runs.

## The process

1. **Build and lint locally.** Flathub's own tooling, not ours:

   ```bash
   flatpak install -y flathub org.flatpak.Builder
   flatpak run --command=flathub-build org.flatpak.Builder --install <manifest>
   flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest <manifest>
   flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo <repo>
   ```

   `make flatpak-lint` wraps the manifest check.

2. **Fork [flathub/flathub](https://github.com/flathub/flathub)**, with *Copy
   the master branch only* **unchecked** — the submission branch is not
   `master`.

   ```bash
   git clone --branch=new-pr git@github.com:<you>/flathub.git && cd flathub
   git checkout -b gtkpass-submission new-pr
   ```

3. **Add the manifest at the repository root**, named exactly
   `io.github.RonnyPfannschmidt.GTKPass.yml`. Note that this differs from this
   repository, where it lives in `build-aux/`; Flathub requires it at the top
   level of the submission.

4. **Open a pull request against the `new-pr` branch** — not `master` — titled
   `Add io.github.RonnyPfannschmidt.GTKPass`. Never merge `master` into the
   submission branch. Comment `bot, build` to trigger a test build, and push
   fixes to the same PR rather than opening a new one.

5. **After approval** the reviewers create
   `github.com/flathub/io.github.RonnyPfannschmidt.GTKPass` and invite you to
   it. The invitation expires in a week and requires 2FA on your GitHub
   account. The build publishes within a couple of hours.

## The part that needs a decision: permissions

The linter rejects the manifest as it stands, and the built repository with it:

```json
{
  "errors": [
    "finish-args-gnupg-filesystem-access",
    "finish-args-has-socket-gpg-agent",
    "metainfo-missing-screenshots",
    "appstream-screenshots-not-mirrored-in-ostree"
  ]
}
```

The last two are the missing screenshots, covered below. The first two are
permissions.

`finish-args-has-socket-ssh-auth` used to be on that list and is not any more:
the manifest no longer requests `--socket=ssh-auth` or `--share=network`. See
the section after next.

These are not mistakes to fix — they are the permissions that make a password
manager work, and Flathub requires each to be justified individually. Errors
are waived through
[exceptions.json](https://github.com/flathub-infra/flatpak-builder-lint/blob/master/flatpak_builder_lint/staticfiles/exceptions.json)
in `flathub-infra/flatpak-builder-lint`, by pull request, granted case by case.
The format is per app id:

```json
"io.github.RonnyPfannschmidt.GTKPass": {
  "stable": {
    "finish-args-has-socket-gpg-agent": "<justification>",
    "finish-args-gnupg-filesystem-access": "<justification>"
  }
}
```

**Both have direct precedent.**
[Identities](https://flathub.org/apps/one.k8ie.Identities), the other GNOME
password-store client, holds exactly these, granted with:

- `finish-args-has-socket-gpg-agent` — *"Needs to be able to use your host's
  GPG agent to decrypt password store entries"*
- `finish-args-gnupg-filesystem-access` — *"Due to how GPG handles working with
  a remote agent, the Flatpak's GPG needs to know which public keys are
  available on the 'remote' host"*

Both apply to GTKPass word for word, and our grants are the narrower ones:
three read-only files rather than `~/.gnupg` wholesale.

## The third permission, and how it was resolved

`--socket=ssh-auth` was the awkward one. It existed so the bundled `pass` could
drive `git` against a remote, and `gitg` holds the same exception only as
*"Predates the linter rule"* — grandfathered, not argued. GTKPass had no
argument to make at all, because nothing in the interface performed a sync.

There is now a sync action, so the argument exists. It is still not the one
being made. **The manifest requests neither `--socket=ssh-auth` nor
`--share=network`**, and users who want sync grant them themselves:

```bash
flatpak override --user --socket=ssh-auth --share=network io.github.RonnyPfannschmidt.GTKPass
```

Static permissions are required to be *"kept to an absolute minimum"*, and most
password stores have no git remote at all. Granting every user network access
and an agent socket for a feature a minority use is the wrong default, and the
override costs those users one command — which the application shows them,
copyable, the first time a sync finds the permission missing.

A Flatpak extension cannot carry the permission instead; that was checked rather
than assumed, and the reasoning is in
[FLATPAK.md](FLATPAK.md#an-extension-cannot-carry-the-permission-instead).

So the submission needs two exceptions rather than three, and both are the ones
Identities already holds word for word.

## What GTKPass already satisfies

| Requirement | State |
| --- | --- |
| Reverse-DNS id, ≥4 components for `io.github.` | `io.github.RonnyPfannschmidt.GTKPass` |
| Id matches the metainfo `<id>` | held by a test |
| Manifest named after the app id | yes, in `build-aux/` |
| Latest runtime at submission time | GNOME 50 |
| Built entirely from source | yes; every source has a sha256 |
| No network access during build | yes; nothing fetches at build time |
| Metainfo present and valid | `appstreamcli validate` runs in the test suite |
| `<developer>` with `id` and `<name>` | yes |
| Release notes with a `<releases>` tag | yes |
| Branding colours, light and dark | yes |
| Desktop file, validated | `desktop-file-validate` runs in the test suite |
| SVG icon | yes, see the caveat below |
| Licence installed to `share/licenses/$FLATPAK_ID` | yes |
| English user interface and metadata | yes |

## What is still missing

- **Screenshots.** Mandatory for graphical applications: at least one
  `<screenshot type="default">` with an `<image>` at a direct URL and a
  `<caption>`. Images hosted in git must be referenced by tag or commit, never
  a branch. GTKPass has none, and they cannot be added honestly until the
  interface is worth photographing — adding an entry still opens a "not
  implemented" dialog.
- **A release tag.** The manifest builds from the working directory
  (`type: dir`) and pins the version with `SETUPTOOLS_SCM_PRETEND_VERSION`. A
  submission needs `type: git` with a tag and commit hash, which means tagging
  a release and letting setuptools-scm derive the version from it.
- **A real icon.** `data/icons/…/*.svg` is a placeholder drawn to fill the
  slot. Flathub reviews icon quality.
- **`secretstorage`**, if the Secret Service backend is meant to work in the
  packaged build. It needs `cryptography`, a Rust build requiring an SDK
  extension.
`--socket=ssh-auth` is no longer on this list: it is not requested, so there is
nothing left to decide.

## Afterwards

Updates are pull requests to the app's own repository under the Flathub
organisation; a bot builds each one. `x-checker-data` is already set on the
`python-gnupg` and `git` sources, so Flathub's external data checker can open
version-bump PRs by itself.

App **verification** — the check mark linking the listing to
`github.com/RonnyPfannschmidt/gtk-pass-ng` — is a separate step, done from the
Flathub developer portal after the app is published.
