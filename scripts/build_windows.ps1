[CmdletBinding()]
param(
    [string]$PythonExecutable = "py",
    [string]$OutputDirectory = "release",
    [switch]$SkipChecks,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $projectRoot $OutputDirectory
$buildRoot = Join-Path $releaseRoot "build"
$standaloneDirectory = Join-Path $buildRoot "srun_client.dist"
$iconPath = Join-Path $projectRoot "srunpy\html\icons\logo.ico"
$entryPoint = Join-Path $projectRoot "srun_client.py"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $Executable $($Arguments -join ' ')"
    }
}

if ($PythonExecutable -eq "py") {
    $pythonCommand = "py"
    $pythonPrefixArguments = @("-3")
} else {
    $pythonCommand = $PythonExecutable
    $pythonPrefixArguments = @()
}

$versionArguments = $pythonPrefixArguments + @(
    "-c",
    "from srunpy.version import __version__; print(__version__)"
)
$applicationVersion = (& $pythonCommand @versionArguments).Trim()
if ($LASTEXITCODE -ne 0 -or -not $applicationVersion) {
    throw "Unable to read the application version with a supported Python interpreter."
}

$runtimeVersionArguments = $pythonPrefixArguments + @(
    "-c",
    "import struct, sys; assert (3, 12) <= sys.version_info[:2] < (3, 15), 'Windows releases require Python 3.12 through 3.14'; assert struct.calcsize('P') == 8, 'Windows releases require a 64-bit Python interpreter'"
)
Invoke-CheckedCommand -Executable $pythonCommand -Arguments $runtimeVersionArguments

if (-not (Test-Path $iconPath)) {
    throw "Required application icon is missing: $iconPath"
}

if (Test-Path $releaseRoot) {
    Remove-Item -Recurse -Force $releaseRoot
}
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null

Push-Location $projectRoot
try {
    if (-not $SkipChecks) {
        Invoke-CheckedCommand -Executable $pythonCommand -Arguments ($pythonPrefixArguments + @("-m", "pytest", "--cov", "--cov-report=term-missing", "--cov-fail-under=80"))
        Invoke-CheckedCommand -Executable $pythonCommand -Arguments ($pythonPrefixArguments + @("-m", "ruff", "check", "srunpy", "tests"))
        Invoke-CheckedCommand -Executable "npm" -Arguments @("ci")
        Invoke-CheckedCommand -Executable "node" -Arguments @("--test", "tests/js/*.test.js")
    }

    $nuitkaArguments = $pythonPrefixArguments + @(
        "-m", "nuitka",
        "--standalone",
        "--assume-yes-for-downloads",
        "--disable-plugin=pywebview",
        "--include-module=webview.platforms.winforms",
        "--include-module=webview.platforms.win32",
        "--windows-console-mode=disable",
        "--output-dir=$buildRoot",
        "--output-filename=SRunClient.exe",
        "--include-package=psutil",
        "--include-data-dir=srunpy/html=srunpy/html",
        "--windows-icon-from-ico=$iconPath",
        "--file-version=$applicationVersion",
        "--product-version=$applicationVersion",
        "--company-name=cjdem",
        "--product-name=SRunPy Campus Network Client",
        "--file-description=SRunPy Campus Network Client",
        $entryPoint
    )
    Invoke-CheckedCommand -Executable $pythonCommand -Arguments $nuitkaArguments

    if (-not (Test-Path (Join-Path $standaloneDirectory "SRunClient.exe"))) {
        throw "Nuitka completed without producing the expected executable."
    }

    $releaseNoticeFiles = @(
        "LICENSE",
        "README.md",
        "SOURCE_CODE.md",
        "THIRD_PARTY_NOTICES.md"
    )
    foreach ($releaseNoticeFile in $releaseNoticeFiles) {
        $noticeSourcePath = Join-Path $projectRoot $releaseNoticeFile
        if (-not (Test-Path $noticeSourcePath)) {
            throw "Required release notice is missing: $noticeSourcePath"
        }
        Copy-Item -Path $noticeSourcePath -Destination $standaloneDirectory -Force
    }

    $portableArchive = Join-Path $releaseRoot "SRunPy-$applicationVersion-win-x64-portable.zip"
    Compress-Archive -Path (Join-Path $standaloneDirectory "*") -DestinationPath $portableArchive

    if (-not $SkipInstaller) {
        $innoCompilerCandidates = @(
            "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )
        $innoCompiler = $innoCompilerCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $innoCompiler) {
            throw "Inno Setup 6 was not found. Install it or use -SkipInstaller."
        }
        $installerScript = Join-Path $projectRoot "packaging\SRunPy.iss"
        Invoke-CheckedCommand -Executable $innoCompiler -Arguments @(
            "/DAppVersion=$applicationVersion",
            "/DSourceDirectory=$standaloneDirectory",
            "/DOutputDirectory=$releaseRoot",
            $installerScript
        )
    }

    $hashManifest = Join-Path $releaseRoot "SHA256SUMS.txt"
    Get-ChildItem -Path $releaseRoot -File |
        Where-Object { $_.Name -ne "SHA256SUMS.txt" } |
        ForEach-Object {
            $fileHash = Get-FileHash -Algorithm SHA256 -Path $_.FullName
            "$($fileHash.Hash.ToLowerInvariant())  $($_.Name)"
        } | Set-Content -Path $hashManifest -Encoding ascii

    Write-Host "Windows release artifacts created in $releaseRoot"
} finally {
    Pop-Location
}
