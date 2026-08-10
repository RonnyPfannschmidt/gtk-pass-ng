# Making a release

```bash
git tag -a v0.1.0 -m "0.1.0"
git push origin v0.1.0
```

That is the whole of it. `.github/workflows/release.yml` does the rest: runs all
of CI, publishes the wheel and sdist to PyPI, and attaches the RPMs and sysext
images to a GitHub release.

No release has been made yet. Everything below describes a pipeline that has
been built and reviewed but not yet run against a real tag.

## Before the first one: PyPI

Publishing uses [trusted publishing][tp], so there is no API token to store,
leak or rotate — PyPI verifies the workflow's identity over OIDC instead. It
needs two things set up once.

**On PyPI**, add a [pending publisher][pending] — the form is under
[Your account → Publishing](https://pypi.org/manage/account/publishing/), and
"pending" is the case where the publisher is configured before the project
exists, PyPI creating it on the first successful upload:

| Field | Value |
| --- | --- |
| PyPI project name | `gtk-pass-ng` |
| Owner | `RonnyPfannschmidt` |
| Repository | `gtk-pass-ng` |
| Workflow | `release.yml` |
| Environment | `pypi` |

**On GitHub**, the repository has to be named `gtk-pass-ng`, because that is what
the reserved publisher records and PyPI matches it against the OIDC claim
exactly. Publishing fails until the rename happens, and a rename afterwards
breaks it again unless the publisher is updated to match.

Also create an environment named `pypi` (Settings → Environments).
It can be empty; it exists so the publishing job is nameable, and so a required
reviewer can be attached to it later if releases should need a second pair of
eyes.

Every field has to match the workflow exactly or the upload is rejected, and
the environment is not optional: `release.yml` declares `environment: pypi`, so
leaving that box empty fails the upload rather than relaxing the check.

[tp]: https://docs.pypi.org/trusted-publishers/
[pending]: https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/

### Why the distribution is called gtk-pass-ng

`gtkpass` on PyPI is an unrelated GTK+3 frontend for `pass`, last released in
2017. `gtk-pass` was tried next and refused: PyPI rejects names that are merely
*similar* to an existing one, and after normalisation those two are. Hence the
suffix.

The import package, the `gtkpass` command, the entry point group and the RPM all
keep the name; only the string PyPI knows differs.

Two consequences worth knowing. The sdist is `gtk_pass_ng-<version>.tar.gz`, PEP
625 having normalised the hyphens, which is why the spec unpacks a directory
named differently from the RPM. And `safety.DISTRIBUTION_NAME` has to match,
because that is the name the guard looks up to decide whether it is running from
an install — get it wrong and the application refuses to start, loudly, which is
at least the right direction.

There is an issue open about claiming the original name.

## What a tag sets off

1. **verify** — the whole of `ci.yml`, called as a reusable workflow: lint,
   types, the suite on two Fedora releases, and the RPM and sysext jobs, which
   install and inspect what they build. Everything else waits for this.
2. **distribution** — builds the sdist and wheel, and checks the version
   setuptools-scm derived is exactly the tag. A tag that is not on the commit
   being built yields `0.1.0.dev3+g1234567`, which would otherwise be published
   as a perfectly valid and completely wrong release.
3. **pypi** — uploads to PyPI.
4. **github-release** — creates the release and attaches the packages *that
   verify already built*, rather than a second build nobody checked.

Running the workflow by hand instead does 1 and 2 and stops: every publishing
step is guarded on the ref being a tag, so a manual run is a dry run and cannot
release by accident.

## Versions

`setuptools-scm` derives the Python version from git, so there is nothing to
edit before tagging. `packaging/build-rpm.sh` derives the RPM's version and
release from git too, in the three states a checkout can be in:

| State | Version | Release | Sorts |
| --- | --- | --- | --- |
| Before any tag | `0.1.0` | `0.1.<date>git<hash>` | before `0.1.0-1` |
| On a tag | the tag, without `v` | `1` | — |
| After a tag | the last tag | `2.<date>git<hash>` | after that release |

The point of the release forms is that upgrades only ever move forwards. A
snapshot taken before the first release upgrades to it; a snapshot taken after
one is newer than it, so `dnf upgrade` will not walk backwards onto the release
it was built from.

The date is the commit's, not the day's, so building a commit twice gives the
same package. A dirty tree appends `.dirty`, because such a build does not
describe the commit it names.

Pre-release tags are not handled: `v0.2.0rc1` gives an RPM version that sorts
*after* `0.2.0`, RPM having no notion of a release candidate short of a `~`
that PEP 440 does not permit. Tag those only if you are prepared to work it out.

## What is released, and what is not

Attached to the release: the wheel and sdist, the RPMs and source RPMs for each
Fedora built, and one sysext image per target.

The sysext images are named `gtkpass-fedora-<release>.raw`, and systemd takes an
extension's identity from that filename — so it will merge on Fedora and refuse
anything else. An image for Silverblue, Bluefin or Bazzite has to be built on
that system, `make sysext` naming it after whatever `/etc/os-release` says.
[PACKAGING.md](PACKAGING.md) explains why an image that merges anywhere is not
worth having.

Nothing is signed. There is no RPM repository, no COPR, and no Flathub listing;
a release is a set of files on a GitHub page, and anyone installing from it is
trusting the transport and not a signature.
