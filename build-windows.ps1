# Compatibility entry point; build and signing steps are in windows.ps1.
param(
    [switch]$Sign,
    [switch]$NoSign,
    [string]$CertificateThumbprint,
    [string]$SignToolPath,
    [string]$TimestampUrl,
    [switch]$MachineCertificateStore
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'windows.ps1') @PSBoundParameters
