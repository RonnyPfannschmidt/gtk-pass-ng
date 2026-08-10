<#
.SYNOPSIS
    Check that a built or installed GTKPass bundle works, as built or installed.

.DESCRIPTION
    The Windows counterpart of packaging\smoke-test-install.sh, and it looks for
    the same class of breakage: resources that did not travel, a schema that
    never reached the compiled cache, entry points that resolve to nothing, and
    the safety guard mistaking a shipped build for somebody's checkout.

    It cannot work the same way. There is no interpreter beside a frozen bundle
    to run assertions against -- the interpreter is inside it -- so the checks
    live in the launcher and this starts the executable to run them. See
    packaging\windows\gtkpass-launcher.py.

.PARAMETER BundleDir
    The directory holding gtkpass.exe: the freshly built dist\windows\gtkpass,
    an unpacked portable zip, or wherever the installer put it.

.PARAMETER TimeoutSeconds
    How long to wait before deciding the executable has hung. A hang is the
    failure mode that a missing DLL or an unreachable display produces, and
    waiting forever for it turns a red build into an abandoned one.
#>
[CmdletBinding()]
param(
    [string]$BundleDir,
    [int]$TimeoutSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $BundleDir) {
    $BundleDir = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path 'dist\windows\gtkpass'
}

$exe = Join-Path $BundleDir 'gtkpass.exe'
if (-not (Test-Path $exe)) {
    throw "no gtkpass.exe in $BundleDir"
}

Write-Host "==> checking $exe"

$report = Join-Path ([System.IO.Path]::GetTempPath()) "gtkpass-self-check-$PID.txt"
Remove-Item -Force $report -ErrorAction SilentlyContinue

$process = Start-Process -FilePath $exe -ArgumentList '--self-check', $report -PassThru
try {
    $process | Wait-Process -Timeout $TimeoutSeconds
} catch {
    $process | Stop-Process -Force -ErrorAction SilentlyContinue
    throw "gtkpass.exe did not finish its self-check within ${TimeoutSeconds}s"
}

if (Test-Path $report) {
    Get-Content $report | ForEach-Object { Write-Host "    $_" }
} else {
    Write-Host "    (no report was written)"
}

if ($process.ExitCode -ne 0) {
    throw "self-check failed with exit code $($process.ExitCode)"
}

Write-Host ""
Write-Host "==> the bundle works"
