# PSSAQ Windows build - PowerShell 5.1+ / Python 3.11+
param(
    [switch]$Sign,
    [switch]$NoSign,
    [string]$CertificateThumbprint = $env:PSSAQ_SIGN_CERT_THUMBPRINT,
    [string]$SignToolPath = $env:PSSAQ_SIGNTOOL,
    [string]$TimestampUrl = $env:PSSAQ_TIMESTAMP_URL,
    [switch]$MachineCertificateStore
)
$ErrorActionPreference = 'Stop'
if ($Sign -and $NoSign) { throw '-Sign and -NoSign cannot be combined.' }
if ($env:OS -ne 'Windows_NT') { throw 'Run this script on Windows to create PSSAQ.exe.' }
# Normal release builds are signed. Unsigned development builds require -NoSign.
$shouldSign = -not $NoSign
$buildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

function Run-Python([string[]] $Arguments) {
    & $buildPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python step failed (exit $LASTEXITCODE): $($Arguments -join ' ')" }
}

Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath $buildPython)) {
        & python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create the Python build environment.' }
    }
    Write-Host '[1/6] Installing build dependencies...'
    Run-Python -Arguments @('-m','pip','install','--upgrade','pip')
    Run-Python -Arguments @('-m','pip','install','--upgrade','-r','requirements.txt')
    $versionOutput = & $buildPython -c 'from pssaq import __version__; print(__version__)'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read PSSAQ version.' }
    $version = "$versionOutput".Trim()
    if ($version -notmatch '^\d+\.\d+(?:\.\d+)?$') { throw 'Invalid PSSAQ version.' }
    $release = Join-Path $PSScriptRoot 'release'
    $exe = Join-Path $release 'PSSAQ.exe'
    $zip = Join-Path $release ("pssaq_v{0}.zip" -f $version)
    New-Item -ItemType Directory -Force -Path $release | Out-Null
    # Remove an older same-version ZIP before any step that can fail.
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip }

    Write-Host '[2/6] Running unit tests...'
    $oldQpa = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = 'offscreen'
        Run-Python -Arguments @('-m','unittest','discover','-v')
    } finally { $env:QT_QPA_PLATFORM = $oldQpa }
    Write-Host '[3/6] Building Windows EXE with SciPy backends and icons...'
    Run-Python -Arguments @('-m','PyInstaller','--noconfirm','--clean','--distpath','release','PSSAQ.spec')
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'PSSAQ.exe not produced' }
    Write-Host '[4/6] Checking the built EXE (imports, window, icon, DSP)...'
    Run-Python -Arguments @('scripts/smoke_exe.py',$exe)

    Write-Host '[5/6] Signing and verifying the Windows EXE...'
    if ($shouldSign) {
        $signArgs = @('scripts/windows_signing.py')
        if ($CertificateThumbprint) { $signArgs += @('--certificate-thumbprint',$CertificateThumbprint) }
        if ($SignToolPath) { $signArgs += @('--signtool',$SignToolPath) }
        if ($TimestampUrl) { $signArgs += @('--timestamp-url',$TimestampUrl) }
        if ($MachineCertificateStore) { $signArgs += '--machine-store' }
        $signArgs += $exe
        Run-Python -Arguments $signArgs
        Write-Host 'Code signing and verification succeeded.' -ForegroundColor Green
    } else {
        Write-Warning 'Unsigned development build (-NoSign).'
    }
    Write-Host '[6/6] Building distributable ZIP...'
    Run-Python -Arguments @('scripts/package_release.py','--version',$version,'--exe',$exe,'--output',$zip)
    if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) { throw 'Release ZIP not produced' }
    Write-Host "Build OK: $exe"
    Write-Host "ZIP OK:   $zip"
} finally { Pop-Location }
