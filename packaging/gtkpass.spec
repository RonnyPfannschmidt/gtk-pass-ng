# RPM spec for GTKPass.
#
# Build it with packaging/build-rpm.sh, which produces the sdist this expects
# and runs rpmbuild in a Fedora container -- the machine this was written on is
# ostree-based and has no rpm-build.
#
# GTKPass has never been tagged, so there is no upstream release to build from.
# The version below is the one build-rpm.sh pins the sdist to, and the actual
# commit is encoded in Release using Fedora's pre-release form: 0.1.0-0.1.<snap>
# sorts before an eventual 0.1.0-1, so a real release will upgrade over any
# snapshot ever installed.

Name:           gtkpass
Version:        0.1.0
Release:        %{?snapshot:0.1.%{snapshot}}%{!?snapshot:1}%{?dist}
Summary:        GTK4 frontend for password stores

License:        MPL-2.0
URL:            https://github.com/RonnyPfannschmidt/gtkpass
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
BuildRequires:  glib2-devel

# The runtime Python dependencies come from the project metadata via
# %%pyproject_install; these are what the metadata cannot express.
Requires:       gtk4 >= 4.10
Requires:       libadwaita >= 1.4
Requires:       gnupg2

# The Pass backend shells out to pass(1), and syncing a store needs git. Both
# are per-backend rather than per-application: a user with only the Direct GPG
# backend configured needs neither, so neither is a hard dependency.
Recommends:     pass
Recommends:     git-core

# The interface is declared in Blueprint and compiled to .ui, but the .ui files
# are committed and ship in the sdist, so blueprint-compiler is not needed here.

%description
GTKPass is a GTK4/Libadwaita frontend for password stores on GNOME/Linux, in
the spirit of qtpass. It is not a password manager of its own: it stores
nothing and owns no format. It presents pluggable backends, one of which reads
and writes the standard passwordstore layout, so an existing store stays usable
from pass(1) and every other tool that speaks it.


%prep
%autosetup -n %{name}-%{version}


%generate_buildrequires
%pyproject_buildrequires


%build
%pyproject_wheel


%install
%pyproject_install
%pyproject_save_files gtkpass

# Desktop integration. Every one of these is named after the application id,
# and tests/test_desktop_integration.py holds them to it.
install -Dpm 0644 data/io.github.RonnyPfannschmidt.GTKPass.desktop \
    %{buildroot}%{_datadir}/applications/io.github.RonnyPfannschmidt.GTKPass.desktop
install -Dpm 0644 data/io.github.RonnyPfannschmidt.GTKPass.metainfo.xml \
    %{buildroot}%{_metainfodir}/io.github.RonnyPfannschmidt.GTKPass.metainfo.xml
install -Dpm 0644 data/icons/hicolor/scalable/apps/io.github.RonnyPfannschmidt.GTKPass.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/io.github.RonnyPfannschmidt.GTKPass.svg

# The schema is installed uncompiled; glib2's file trigger recompiles the
# system cache on install and again on removal. Compiling it here instead would
# ship a gschemas.compiled that overwrites every other application's schemas.
install -Dpm 0644 data/io.github.RonnyPfannschmidt.GTKPass.gschema.xml \
    %{buildroot}%{_datadir}/glib-2.0/schemas/io.github.RonnyPfannschmidt.GTKPass.gschema.xml


%check
desktop-file-validate \
    %{buildroot}%{_datadir}/applications/io.github.RonnyPfannschmidt.GTKPass.desktop
appstream-util validate-relax --nonet \
    %{buildroot}%{_metainfodir}/io.github.RonnyPfannschmidt.GTKPass.metainfo.xml

# Catches a schema that would abort the application at startup: Gio.Settings
# calls g_error() on one it cannot parse, which kills the process outright.
glib-compile-schemas --strict --dry-run \
    %{buildroot}%{_datadir}/glib-2.0/schemas

# The test suite is not run here. It needs a display, a private D-Bus session
# and a GPG key, which is xvfb-run dbus-run-session and a scratch store built
# on the fly -- see `make test`, which is where that gate lives.


%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/gtkpass
%{_datadir}/applications/io.github.RonnyPfannschmidt.GTKPass.desktop
%{_metainfodir}/io.github.RonnyPfannschmidt.GTKPass.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/io.github.RonnyPfannschmidt.GTKPass.svg
%{_datadir}/glib-2.0/schemas/io.github.RonnyPfannschmidt.GTKPass.gschema.xml


%changelog
* Sun Aug 09 2026 Ronny Pfannschmidt <opensource@ronnypfannschmidt.de> - 0.1.0-1
- Initial packaging.
