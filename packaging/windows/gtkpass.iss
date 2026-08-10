; Inno Setup script for the GTKPass installer.
;
; Compiled by packaging\windows\build.ps1, which passes every path and the
; version in on the command line -- nothing here is discovered, so compiling
; this file by hand fails with a clear message rather than producing an
; installer built around whatever happened to be on disk.
;
; The install is per-user by default and needs no administrator. A password
; manager has no business writing to Program Files or to the machine-wide
; registry on a shared computer, and an elevated installer is the one part of
; shipping a desktop application that a user cannot inspect before it runs.
; Someone who wants a machine-wide install can still ask for it: Inno Setup
; offers the choice when PrivilegesRequiredOverridesAllowed says it may.

#ifndef AppVersion
  #error Compile this through packaging\windows\build.ps1; it supplies AppVersion and the paths.
#endif

#define AppName "GTKPass"
#define AppId "io.github.RonnyPfannschmidt.GTKPass"
#define AppPublisher "Ronny Pfannschmidt"
#define AppUrl "https://github.com/RonnyPfannschmidt/gtk-pass-ng"

[Setup]
; Generated once and never changed: this is what tells Windows that an
; installer is an upgrade of what is already there rather than a second
; application. A new GUID here would leave every previously installed version
; behind, uninstallable except by hand.
AppId={{8F3B1C42-6A5D-4E27-9B0E-2C7D5A1F4E88}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersionInfo}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile={#RepoRoot}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=gtkpass-{#AppFileVersion}-windows-x64-setup
SetupIconFile={#RepoRoot}\data\icons\{#AppId}.ico
UninstallDisplayIcon={app}\gtkpass.exe
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
; The bundle is 64-bit throughout -- gvsbuild ships no 32-bit GTK4 -- so say so
; rather than letting it install somewhere it cannot run.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\gtkpass.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\gtkpass.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\gtkpass.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller unpacks nothing here in a onedir build, but Python does: the
; __pycache__ directories a run leaves behind are not ours to enumerate, and
; without this the install directory survives the uninstall holding them.
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"
