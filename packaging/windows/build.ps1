<#
.SYNOPSIS
    Build the Windows executable, the portable zip and the installer.

.DESCRIPTION
    GTK4, libadwaita and PyGObject are taken prebuilt from a pinned gvsbuild
    release rather than compiled here. gvsbuild is the GTK project's own MSVC
    build of the stack, and its GTK4 release archive carries libadwaita, the
    Adwaita icon theme, the introspection typelibs and -- the part that decides
    everything else -- PyGObject and pycairo as wheels, because PyGObject is
    published to PyPI as a source distribution only and there is no other way to
    get it onto Windows without a compiler and the whole GTK stack's headers.

    Those wheels are built against one Python version. It is not a preference:
    a cp314 wheel does not install on 3.13, and the interpreter running this
    script is the one the bundle will carry, so the check below is fatal rather
    than a warning. Which version that is comes from the gvsbuild release, and
    changing the pin means changing the Python alongside it.

    Everything lands under build\windows (working files, reusable) and
    dist\windows (the artefacts).

.PARAMETER GvsbuildVersion
    The gvsbuild release to take the GTK stack from. Pinned deliberately: an
    unpinned "latest" would change the GTK version, and the required Python
    version, under a build that was working yesterday.

.PARAMETER Wheel
    Freeze this already-built wheel instead of building one from the working
    tree. CI passes the wheel its distribution job produced -- the same file the
    release publishes and the Linux jobs install -- so that what ships inside
    the Windows bundle is what was tested elsewhere, rather than a second build
    of the same commit that nothing else ever ran.

.PARAMETER SkipInstaller
    Build the executable and the zip, and stop before Inno Setup. For a machine
    that has no ISCC.exe.

.EXAMPLE
    pwsh -File packaging\windows\build.ps1
#>
[CmdletBinding()]
param(
    [string]$GvsbuildVersion = '2026.8.0',
    [string]$ExpectedPythonVersion = '3.14',
    [string]$Wheel,
    [switch]$SkipInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is glacial with it

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$BuildDir = Join-Path $RepoRoot 'build\windows'
$DistDir = Join-Path $RepoRoot 'dist\windows'
$GtkRoot = Join-Path $BuildDir 'gtk'
$StageDir = Join-Path $BuildDir 'stage'
$VenvDir = Join-Path $BuildDir 'venv'
$AppId = 'io.github.RonnyPfannschmidt.GTKPass'

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Invoke-Checked {
    <#
        PowerShell does not stop on a non-zero exit from a native command,
        whatever $ErrorActionPreference says, so every one of them goes through
        here. A build that carried on past a failed pip install would produce a
        bundle missing whatever that install was for, and say nothing.
    #>
    param([Parameter(Mandatory)][string]$Executable, [string[]]$Arguments)

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Expand-Zip {
    <#
        Expand-Archive is the portable answer and it is unusably slow here: the
        GTK stack is fifteen thousand small files, and it walks them one at a
        time through the pipeline. bsdtar ships with Windows itself and reads
        zip, so it is preferred and Expand-Archive is what happens when it is
        somehow absent.
    #>
    param([string]$Archive, [string]$Destination)

    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    if (Get-Command 'tar.exe' -ErrorAction SilentlyContinue) {
        Invoke-Checked 'tar.exe' @('-xf', $Archive, '-C', $Destination)
    } else {
        Expand-Archive -Path $Archive -DestinationPath $Destination -Force
    }
}

function Compress-Directory {
    param([string]$Directory, [string]$Archive)

    Remove-Item -Force $Archive -ErrorAction SilentlyContinue
    if (Get-Command 'tar.exe' -ErrorAction SilentlyContinue) {
        # -a picks the format from the name; the path is relative to the parent
        # so the zip holds gtkpass\... rather than an absolute path.
        Push-Location (Split-Path -Parent $Directory)
        try {
            Invoke-Checked 'tar.exe' @('-a', '-cf', $Archive, (Split-Path -Leaf $Directory))
        } finally {
            Pop-Location
        }
    } else {
        Compress-Archive -Path $Directory -DestinationPath $Archive
    }
}

New-Item -ItemType Directory -Force -Path $BuildDir, $DistDir | Out-Null

# -- the interpreter -------------------------------------------------------

Write-Step "Checking the interpreter against the gvsbuild wheels"

$pythonVersion = (& python -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if ($LASTEXITCODE -ne 0) { throw "no python on PATH" }
if ($pythonVersion -ne $ExpectedPythonVersion) {
    throw @"
Python $pythonVersion is on PATH, but gvsbuild $GvsbuildVersion ships its
PyGObject and pycairo wheels built for Python $ExpectedPythonVersion, and a
wheel does not install on another version.

Either put Python $ExpectedPythonVersion on PATH, or -- if a newer gvsbuild
release moved to a different one -- pass -ExpectedPythonVersion along with
-GvsbuildVersion and update the defaults in this script.
"@
}
Write-Host "Python $pythonVersion"

# -- the GTK stack ---------------------------------------------------------

$gtkMarker = Join-Path $GtkRoot 'bin\glib-compile-schemas.exe'
if (Test-Path $gtkMarker) {
    Write-Step "Reusing the GTK stack already unpacked in $GtkRoot"
} else {
    Write-Step "Fetching gvsbuild $GvsbuildVersion"

    $archiveName = "GTK4_Gvsbuild_${GvsbuildVersion}_x64.zip"
    $archive = Join-Path $BuildDir $archiveName
    if (-not (Test-Path $archive)) {
        $url = "https://github.com/wingtk/gvsbuild/releases/download/$GvsbuildVersion/$archiveName"
        Write-Host "downloading $url"
        Invoke-WebRequest -Uri $url -OutFile $archive
    }

    Write-Host "unpacking into $GtkRoot"
    Remove-Item -Recurse -Force $GtkRoot -ErrorAction SilentlyContinue
    Expand-Zip -Archive $archive -Destination $GtkRoot

    if (-not (Test-Path $gtkMarker)) {
        throw "$archiveName did not contain bin\glib-compile-schemas.exe; the archive layout has changed"
    }
}

$gtkBin = Join-Path $GtkRoot 'bin'
$typelibDir = Join-Path $GtkRoot 'lib\girepository-1.0'

# PyInstaller resolves the shared library behind each typelib by looking it up
# the way the loader would, and glib-compile-schemas has to be findable too, so
# the GTK bin directory is on PATH for the build and not only for the run.
$env:PATH = "$gtkBin;$env:PATH"

# Where the typelibs are. Without this, gi.require_version('Gtk', '4.0') fails
# with "Namespace Gtk not available" during the build, PyInstaller's gi hook
# concludes the module is unavailable and collects *nothing* -- and the failure
# does not surface until the finished bundle is started.
if (-not (Test-Path $typelibDir)) {
    throw "no typelibs in $typelibDir; this gvsbuild release has a different layout"
}
$env:GI_TYPELIB_PATH = $typelibDir

# -- the environment the bundle is frozen out of ---------------------------

Write-Step "Creating the build environment"

if (-not (Test-Path (Join-Path $VenvDir 'Scripts\python.exe'))) {
    Invoke-Checked python @('-m', 'venv', $VenvDir)
}
$venvPython = Join-Path $VenvDir 'Scripts\python.exe'

# Python 3.8 stopped searching PATH for the DLLs an extension module depends on,
# so having the GTK bin directory on PATH does not let `import gi` find
# libgobject: os.add_dll_directory is the only thing that does, and PyGObject
# does not call it itself -- there is no Windows DLL handling in gi/__init__.py
# at all, which is why "DLL load failed while importing _gi" is the first thing
# anyone hits here.
#
# A .pth file rather than a call in a script, because it has to reach *every*
# interpreter started from this environment. PyInstaller asks what a typelib
# needs from isolated subprocesses of its own, and those inherit the environment
# but nothing the parent process did to itself.
$dllPath = Join-Path $VenvDir 'Lib\site-packages\_gtkpass_gvsbuild_dlls.pth'
# WriteAllText rather than Set-Content: it is UTF-8 without a BOM on every
# PowerShell, and a BOM at the head of a .pth file is a line Python cannot read.
[System.IO.File]::WriteAllText(
    $dllPath, 'import os; os.add_dll_directory(r"' + $gtkBin + '")' + "`n")

Invoke-Checked $venvPython @('-m', 'pip', 'install', '--upgrade', '--quiet', 'pip', 'build', 'pyinstaller')

Write-Step "Installing PyGObject and pycairo from the gvsbuild wheels"

$wheelDir = Join-Path $GtkRoot 'wheels'
$gtkWheels = @(Get-ChildItem -Path $wheelDir -Filter '*.whl' -ErrorAction SilentlyContinue)
if ($gtkWheels.Count -eq 0) {
    throw "no wheels in $wheelDir; this gvsbuild release does not ship PyGObject, and it cannot be built here"
}
$gtkWheels | ForEach-Object { Write-Host "  $($_.Name)" }
Invoke-Checked $venvPython (@('-m', 'pip', 'install', '--force-reinstall', '--no-deps') + ($gtkWheels | ForEach-Object { $_.FullName }))

Write-Step "Installing the gtkpass wheel"

# A wheel, never an install from the working tree. An in-tree or editable
# install records itself as one in direct_url.json, and safety.py reads exactly
# that to decide whether what is running is somebody's checkout -- so a bundle
# frozen out of one would ship refusing to open its owner's password store.
if ($Wheel) {
    $wheelPath = (Resolve-Path $Wheel).Path
    Write-Host "using $wheelPath"
} else {
    Invoke-Checked $venvPython @('-m', 'build', '--wheel', '--outdir', (Join-Path $BuildDir 'wheel'), $RepoRoot)
    $wheelPath = (Get-ChildItem -Path (Join-Path $BuildDir 'wheel') -Filter 'gtk_pass_ng-*.whl' |
        Sort-Object LastWriteTime | Select-Object -Last 1).FullName
}
# Two steps, and not for the sake of it. `pip install --force-reinstall <wheel>`
# reinstalls the *dependencies* as well, and PyGObject and pycairo are
# dependencies: pip went to PyPI, found the source distributions, built them
# against the GTK stack that happened to be on PATH, and replaced the wheels
# gvsbuild had built with the results. So the application is reinstalled on its
# own, and the dependency resolution runs separately, where PyGObject and
# pycairo are already satisfied and are left alone.
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--force-reinstall', '--no-deps', $wheelPath)
Invoke-Checked $venvPython @('-m', 'pip', 'install', $wheelPath)

Write-Step "Checking that GTK is reachable from Python"

# Before PyInstaller rather than after. Its gi hook treats an unimportable
# module as an absent one: it collects nothing, says so in a line nobody reads,
# and the build succeeds -- producing a bundle that fails on the first
# gi.require_version, which is the last place anyone looks for a packaging
# fault.
Invoke-Checked $venvPython @('-c', @'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
print(f"    GTK {Gtk.MAJOR_VERSION}.{Gtk.MINOR_VERSION}.{Gtk.MICRO_VERSION}, "
      f"libadwaita {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}.{Adw.MICRO_VERSION}")
'@)

$version = (& $venvPython -c "from importlib.metadata import version; print(version('gtk-pass-ng'))")
if ($LASTEXITCODE -ne 0) { throw "the wheel installed but its metadata could not be read" }
Write-Host "version $version"

# -- what the bundle carries beyond the code -------------------------------

Write-Step "Staging the GSettings schema"

Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
$schemaStage = Join-Path $StageDir 'share\glib-2.0\schemas'
New-Item -ItemType Directory -Force -Path $schemaStage | Out-Null

# The *source* XML, not a compiled cache, and this is not a detail.
#
# PyInstaller compiles the schemas itself: it gathers every .gschema.xml headed
# for share\glib-2.0\schemas, runs glib-compile-schemas over the lot, and
# discards any gschemas.compiled it was handed -- so a pre-compiled file staged
# here would be dropped, silently, and the application would ship unable to find
# its own settings. Handing over the source instead is what gets this
# application's schema into the same cache as GTK's, which is what the file is:
# one cache per directory, not one per package.
#
# GTK's own schemas arrive on their own, collected from the gvsbuild prefix by
# PyInstaller's GLib hook. They have to be in that cache too -- a GSettings
# lookup that misses calls g_error(), and the process aborts with no traceback
# and nothing said. The bundle's self-check looks one of them up for exactly
# that reason.
Copy-Item -Path (Join-Path $RepoRoot 'data\*.gschema.xml') -Destination $schemaStage

# glib-compile-schemas is on PATH because the GTK bin directory is, above.
# Without it PyInstaller warns and collects the sources uncompiled, which GLib
# does not read.
if (-not (Get-Command 'glib-compile-schemas.exe' -ErrorAction SilentlyContinue)) {
    throw "glib-compile-schemas.exe is not on PATH; PyInstaller needs it to build the schema cache"
}

Write-Step "Staging the application icon"

$iconStage = Join-Path $StageDir 'share\icons\hicolor\scalable\apps'
New-Item -ItemType Directory -Force -Path $iconStage | Out-Null
Copy-Item -Path (Join-Path $RepoRoot "data\icons\hicolor\scalable\apps\$AppId.svg") -Destination $iconStage

# -- freezing --------------------------------------------------------------

Write-Step "Freezing with PyInstaller"

$env:GTKPASS_REPO_ROOT = $RepoRoot
$env:GTKPASS_STAGING = $StageDir

$bundleDir = Join-Path $DistDir 'gtkpass'
Remove-Item -Recurse -Force $bundleDir -ErrorAction SilentlyContinue
Invoke-Checked $venvPython @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--clean',
    '--distpath', $DistDir,
    '--workpath', (Join-Path $BuildDir 'pyinstaller'),
    (Join-Path $PSScriptRoot 'gtkpass.spec')
)

$exe = Join-Path $bundleDir 'gtkpass.exe'
if (-not (Test-Path $exe)) { throw "PyInstaller produced no $exe" }

# -- the artefacts ---------------------------------------------------------

# A version like 0.2.1.dev5+g1234567 is a perfectly good PEP 440 version and a
# poor filename; the local-version separator is the only character in it that
# Windows and the shells around it object to.
$fileVersion = $version -replace '\+', '.'

Write-Step "Packing the portable zip"

$zip = Join-Path $DistDir "gtkpass-$fileVersion-windows-x64.zip"
Compress-Directory -Directory $bundleDir -Archive $zip
Write-Host "$zip"

if ($SkipInstaller) {
    Write-Step "Skipping the installer as asked"
    exit 0
}

Write-Step "Building the installer"

$isccCommand = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
$iscc = if ($isccCommand) { $isccCommand.Source } else { $null }
if (-not $iscc) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) {
    throw @"
Inno Setup's compiler (ISCC.exe) was not found. Install Inno Setup 6, or pass
-SkipInstaller to build only the executable and the portable zip. GitHub's
windows runners have it preinstalled.
"@
}

# Inno Setup writes the version into the installer's own VERSIONINFO resource,
# and Windows will only take four numbers there. The release part of the
# version is what those are; anything a development version appends is carried
# by AppVersion, which is a free string and what the user is shown.
$quad = if ($version -match '^(\d+)\.(\d+)\.(\d+)') { "$($Matches[1]).$($Matches[2]).$($Matches[3]).0" } else { '0.0.0.0' }

Invoke-Checked $iscc @(
    "/DAppVersion=$version",
    "/DAppVersionInfo=$quad",
    "/DAppFileVersion=$fileVersion",
    "/DRepoRoot=$RepoRoot",
    "/DBundleDir=$bundleDir",
    "/DOutputDir=$DistDir",
    (Join-Path $PSScriptRoot 'gtkpass.iss')
)

Write-Step "Done"
Get-ChildItem -Path $DistDir -File | ForEach-Object { Write-Host "  $($_.Name)  $([math]::Round($_.Length / 1MB, 1)) MB" }
