# PSSAQ Windows build - PowerShell 5.1+ / Python 3.11+
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$version = '0.93'
$release = Join-Path $PSScriptRoot 'release'
$exe = Join-Path $release 'PSSAQ.exe'
$zip = Join-Path $release ("pssaq_v{0}.zip" -f $version)
$buildPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

function Run-Python([string[]] $Arguments) {
    & $buildPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python step failed (exit $LASTEXITCODE): $($Arguments -join ' ')" }
}

if ($env:OS -ne 'Windows_NT') { throw 'Run this script on Windows to create PSSAQ.exe.' }
if (-not (Test-Path -LiteralPath $buildPython)) {
    & python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the Python build environment.' }
}
Write-Host '[1/5] Installing build dependencies...'
Run-Python -Arguments @('-m','pip','install','--upgrade','pip')
Run-Python -Arguments @('-m','pip','install','--upgrade','-r','requirements.txt')
Write-Host '[2/5] Running unit tests...'
$oldQpa = $env:QT_QPA_PLATFORM
try {
    $env:QT_QPA_PLATFORM = 'offscreen'
    Run-Python -Arguments @('-m','unittest','discover','-v')
} finally { $env:QT_QPA_PLATFORM = $oldQpa }
Write-Host '[3/5] Building Windows EXE with SciPy backends and icons...'
New-Item -ItemType Directory -Force -Path $release | Out-Null
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip }
Run-Python -Arguments @('-m','PyInstaller','--noconfirm','--clean','--distpath','release','PSSAQ.spec')
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'PSSAQ.exe not produced' }
Write-Host '[4/5] Checking the built EXE (imports, window, icon, DSP)...'
Run-Python -Arguments @('scripts/smoke_exe.py',$exe)
Write-Host '[5/5] Building distributable ZIP...'
Run-Python -Arguments @('scripts/package_release.py','--version',$version,'--exe',$exe,'--output',$zip)
if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) { throw 'Release ZIP not produced' }
Write-Host "Build OK: $exe"
Write-Host "ZIP OK:   $zip"

