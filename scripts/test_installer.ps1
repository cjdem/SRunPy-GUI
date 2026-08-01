[CmdletBinding()]
param(
    [string]$InstallerPath = "",
    [string]$PythonExecutable = "py",
    [string]$OutputDirectory = "release",
    [switch]$SkipBuild
)

# Silently install, upgrade, and uninstall the SRunPy installer in the current
# Windows session, verifying each phase. Run this in an isolated Windows
# environment (VM or CI) -- it mutates the per-user install location and the
# HKCU uninstall registry, and it must not run while SRunPy is in use.
#
# Examples:
#   .\scripts\test_installer.ps1                       # builds, then tests install
#   .\scripts\test_installer.ps1 -InstallerPath .\release\SRunPy-1.0.9.1-win-x64-setup.exe
#   .\scripts\test_installer.ps1 -SkipBuild -PythonExecutable python

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$appInstallDirectory = Join-Path $env:LOCALAPPDATA "Programs\SRunPy"
$uninstallRegistryPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"

function Assert-PathExists {
    param([string]$Path, [string]$What)
    if (-not (Test-Path $Path)) {
        throw "Expected $What to exist but it does not: $Path"
    }
    Write-Host "OK: $What present at $Path"
}

function Assert-PathAbsent {
    param([string]$Path, [string]$What)
    if (Test-Path $Path) {
        throw "Expected $What to be removed but it still exists: $Path"
    }
    Write-Host "OK: $What removed ($Path)"
}

if (-not $InstallerPath) {
    if ($SkipBuild) {
        throw "-InstallerPath was not provided and -SkipBuild was used."
    }
    Write-Host "Building installer for the installer lifecycle test..."
    & (Join-Path $projectRoot "scripts\build_windows.ps1") -PythonExecutable $PythonExecutable -OutputDirectory $OutputDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed with exit code $LASTEXITCODE"
    }
    $InstallerPath = Get-ChildItem (Join-Path $projectRoot $OutputDirectory) -Filter "*-setup.exe" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

$InstallerPath = (Resolve-Path $InstallerPath).Path
Write-Host "Testing installer: $InstallerPath"
Assert-PathExists -Path $InstallerPath -What "installer"

# 1. Silent install ------------------------------------------------------------
Write-Host "Installing silently..."
$installArguments = @($InstallerPath, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=install.log")
Start-Process -FilePath $InstallerPath -ArgumentList $installArguments -Wait
Assert-PathExists -Path (Join-Path $appInstallDirectory "SRunClient.exe") -What "installed executable"
$uninstallKeys = Get-ChildItem $uninstallRegistryPath -ErrorAction SilentlyContinue |
    Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -like "SRunPy*" }
if (-not $uninstallKeys) {
    throw "No SRunPy uninstall registry entry was created."
}
Write-Host "OK: uninstall registry entry present"

# 2. Silent upgrade (same installer again exercises the update path) -----------
Write-Host "Re-running installer silently to exercise upgrade..."
$upgradeArguments = @($InstallerPath, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=upgrade.log")
Start-Process -FilePath $InstallerPath -ArgumentList $upgradeArguments -Wait
Assert-PathExists -Path (Join-Path $appInstallDirectory "SRunClient.exe") -What "upgraded executable"

# 3. Silent uninstall ----------------------------------------------------------
Write-Host "Uninstalling silently..."
$uninstallString = Get-ItemProperty $uninstallKeys[0].PSPath |
    Select-Object -ExpandProperty UninstallString
if ($uninstallString) {
    $uninstallArguments = @($uninstallString, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=uninstall.log")
    Start-Process -FilePath $uninstallString -ArgumentList $uninstallArguments -Wait
} else {
    throw "Uninstall command could not be read from the registry."
}
Assert-PathAbsent -Path (Join-Path $appInstallDirectory "SRunClient.exe") -What "uninstalled executable"

Write-Host "Installer lifecycle test passed: install, upgrade, uninstall."
