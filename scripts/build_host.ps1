[CmdletBinding()]
param(
    [switch]$ConfigureOnly,
    [switch]$ProtocolOnly,
    [switch]$Test,
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$HostDir = Join-Path $Root "host"
$BuildDir = Join-Path $HostDir "build"
$WebView2Version = "1.0.4129.50"
$Vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"

function Fail([string]$Message) {
    Write-Error $Message
    exit 1
}

function Find-VisualStudio {
    if (-not (Test-Path -LiteralPath $Vswhere)) {
        Fail "vswhere.exe not found. Install Visual Studio 2022 Build Tools with the C++ workload."
    }
    $path = & $Vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($LASTEXITCODE -ne 0 -or -not $path) {
        Fail "Visual Studio 2022 with MSVC x64 tools was not found."
    }
    return $path.Trim()
}

function Find-WebView2Sdk([string]$VisualStudioPath) {
    if ($env:KAZARIPLAY_WEBVIEW2_SDK_ROOT) {
        $candidates = @($env:KAZARIPLAY_WEBVIEW2_SDK_ROOT)
    } else {
        $candidates = @(
            (Join-Path $HostDir ".packages\Microsoft.Web.WebView2.$WebView2Version"),
            (Join-Path $env:USERPROFILE ".nuget\packages\microsoft.web.webview2\$WebView2Version")
        )
    }

    foreach ($candidate in $candidates) {
        if (-not $candidate) { continue }
        $header = Join-Path $candidate "build\native\include\WebView2.h"
        $library = Join-Path $candidate "build\native\x64\WebView2LoaderStatic.lib"
        if ((Test-Path -LiteralPath $header) -and (Test-Path -LiteralPath $library)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $nuget = Get-Command nuget.exe -ErrorAction SilentlyContinue
    if (-not $nuget) {
        $nuget = Get-ChildItem -Path (Join-Path $VisualStudioPath "Common7") -Filter nuget.exe -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
    if (-not $nuget) {
        $toolDir = Join-Path $HostDir ".tools"
        $nugetPath = Join-Path $toolDir "nuget.exe"
        if (-not (Test-Path -LiteralPath $nugetPath)) {
            New-Item -ItemType Directory -Path $toolDir -Force | Out-Null
            Write-Host "Downloading nuget.exe..."
            Invoke-WebRequest -UseBasicParsing -Uri "https://dist.nuget.org/win-x86-commandline/latest/nuget.exe" -OutFile $nugetPath
        }
        $nuget = Get-Item -LiteralPath $nugetPath
    } else {
        $nuget = Get-Item -LiteralPath $nuget.Source
    }

    $packagesDir = Join-Path $HostDir ".packages"
    New-Item -ItemType Directory -Path $packagesDir -Force | Out-Null
    Write-Host "Restoring Microsoft.Web.WebView2 $WebView2Version..."
    & $nuget.FullName install (Join-Path $HostDir "packages.config") -OutputDirectory $packagesDir -NonInteractive
    if ($LASTEXITCODE -ne 0) {
        Fail "NuGet restore failed."
    }

    $installed = Join-Path $packagesDir "Microsoft.Web.WebView2.$WebView2Version"
    $header = Join-Path $installed "build\native\include\WebView2.h"
    $library = Join-Path $installed "build\native\x64\WebView2LoaderStatic.lib"
    if (-not (Test-Path -LiteralPath $header) -or -not (Test-Path -LiteralPath $library)) {
        Fail "WebView2 SDK $WebView2Version was restored without the expected native headers or x64 loader."
    }
    return (Resolve-Path -LiteralPath $installed).Path
}

$VisualStudio = Find-VisualStudio
$CMake = Join-Path $VisualStudio "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
$CTest = Join-Path $VisualStudio "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\ctest.exe"
if (-not (Test-Path -LiteralPath $CMake)) {
    Fail "CMake was not found in Visual Studio at $CMake"
}
if (-not (Test-Path -LiteralPath $CTest)) {
    Fail "CTest was not found in Visual Studio at $CTest"
}

$BuildHost = -not $ProtocolOnly
$SdkRoot = ""
if ($BuildHost) {
    $SdkRoot = Find-WebView2Sdk $VisualStudio
}

Write-Host "Visual Studio: $VisualStudio"
Write-Host "CMake: $CMake"
Write-Host "WebView2 SDK: $(if ($SdkRoot) { $SdkRoot } else { '(not required for protocol-only configuration)' })"
Write-Host "Build directory: $BuildDir"

$configureArgs = @(
    "-S", $HostDir,
    "-B", $BuildDir,
    "-G", "Visual Studio 17 2022",
    "-A", "x64",
    "-DKAZARIPLAY_BUILD_HOST=$(if ($BuildHost) { 'ON' } else { 'OFF' })"
)
if ($SdkRoot) {
    $configureArgs += "-DKAZARIPLAY_WEBVIEW2_SDK_ROOT=$SdkRoot"
}

& $CMake @configureArgs
if ($LASTEXITCODE -ne 0) {
    Fail "CMake configure failed."
}

if ($Target) {
    & $CMake --build $BuildDir --config Release --target $Target
    if ($LASTEXITCODE -ne 0) {
        Fail "Build target '$Target' failed."
    }
}

if ($Test) {
    & $CTest --test-dir $BuildDir -C Release --output-on-failure
    if ($LASTEXITCODE -ne 0) {
        Fail "CTest failed."
    }
}

if (-not $ConfigureOnly -and -not $Target -and -not $Test -and $BuildHost) {
    & $CMake --build $BuildDir --config Release --target KazariPlayHost
    if ($LASTEXITCODE -ne 0) {
        Fail "KazariPlayHost build failed."
    }
}
