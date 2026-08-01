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

function Invoke-CheckedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $true)]
        [string]$What
    )

    $process = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "$What failed with exit code $($process.ExitCode): $FilePath $($ArgumentList -join ' ')"
    }
    Write-Host "OK: $What completed"
}

function Split-CommandLine {
    param([Parameter(Mandatory = $true)][string]$CommandLine)

    $text = $CommandLine.Trim()
    if ($text.StartsWith('"')) {
        $closingQuote = $text.IndexOf('"', 1)
        if ($closingQuote -lt 0) {
            throw "Unable to parse quoted executable path from uninstall command: $CommandLine"
        }
        $filePath = $text.Substring(1, $closingQuote - 1)
        $arguments = $text.Substring($closingQuote + 1).Trim()
    } elseif ($text -match '^(?<file>.*?\.exe)(?:\s+(?<arguments>.*))?$') {
        $filePath = $Matches.file
        $arguments = if ($Matches.arguments) { $Matches.arguments } else { "" }
    } else {
        throw "Unable to parse executable path from uninstall command: $CommandLine"
    }

    [PSCustomObject]@{
        FilePath = $filePath
        Arguments = $arguments
    }
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
$installArguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=install.log")
Invoke-CheckedProcess -FilePath $InstallerPath -ArgumentList $installArguments -What "Silent install"
Assert-PathExists -Path (Join-Path $appInstallDirectory "SRunClient.exe") -What "installed executable"
$uninstallKeys = Get-ChildItem $uninstallRegistryPath -ErrorAction SilentlyContinue |
    Where-Object { (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).DisplayName -like "SRunPy*" }
if (-not $uninstallKeys) {
    throw "No SRunPy uninstall registry entry was created."
}
Write-Host "OK: uninstall registry entry present"

# 2. Silent upgrade (same installer again exercises the update path) -----------
Write-Host "Re-running installer silently to exercise upgrade..."
$upgradeArguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=upgrade.log")
Invoke-CheckedProcess -FilePath $InstallerPath -ArgumentList $upgradeArguments -What "Silent upgrade"
Assert-PathExists -Path (Join-Path $appInstallDirectory "SRunClient.exe") -What "upgraded executable"

# 3. Silent uninstall ----------------------------------------------------------
Write-Host "Uninstalling silently..."
$uninstallString = Get-ItemProperty $uninstallKeys[0].PSPath |
    Select-Object -ExpandProperty UninstallString
if ($uninstallString) {
    $uninstallCommand = Split-CommandLine -CommandLine $uninstallString
    Assert-PathExists -Path $uninstallCommand.FilePath -What "uninstaller executable"
    $uninstallArguments = @()
    if ($uninstallCommand.Arguments) {
        $uninstallArguments += $uninstallCommand.Arguments
    }
    $uninstallArguments += @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=uninstall.log")
    Invoke-CheckedProcess -FilePath $uninstallCommand.FilePath -ArgumentList $uninstallArguments -What "Silent uninstall"
} else {
    throw "Uninstall command could not be read from the registry."
}
Assert-PathAbsent -Path (Join-Path $appInstallDirectory "SRunClient.exe") -What "uninstalled executable"

Write-Host "Installer lifecycle test passed: install, upgrade, uninstall."
