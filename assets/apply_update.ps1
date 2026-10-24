param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
$job = $null
$swapped = $false
$stage = [System.IO.Path]::GetDirectoryName($Manifest)
$log = Join-Path $stage 'update.log'

function Log([string]$message) {
    $line = ('{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $message)
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
    Write-Host $message
}

try {
    # A restart must never use the previous onefile process's temporary files.
    foreach ($entry in @(Get-ChildItem Env:)) {
        if ($entry.Name -like '_PYI_*' -or $entry.Name -eq '_MEIPASS2') {
            [Environment]::SetEnvironmentVariable($entry.Name, $null, 'Process')
        }
    }
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    $job = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    Log 'Waiting for PSSAQ to exit...'
    $oldProcess = Get-Process -Id ([int]$job.process_id) -ErrorAction SilentlyContinue
    if ($null -ne $oldProcess -and -not $oldProcess.WaitForExit(30000)) {
        throw 'PSSAQ has not exited. The installed EXE has not been changed.'
    }
    if ((Get-FileHash -LiteralPath $job.incoming -Algorithm SHA256).Hash -ne $job.sha256) {
        throw 'Staged EXE checksum mismatch.'
    }
    Log 'Checking the new EXE before installation...'
    $report = Join-Path $stage 'startup.json'
    $quotedReport = '"' + $report + '"'
    $previousQpa = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = 'offscreen'
        $probeInfo = New-Object System.Diagnostics.ProcessStartInfo
        $probeInfo.FileName = [string]$job.incoming
        $probeInfo.Arguments = '--self-test --report ' + $quotedReport
        $probeInfo.WorkingDirectory = $stage
        $probeInfo.UseShellExecute = $false
        $probeInfo.CreateNoWindow = $true
        $probe = [System.Diagnostics.Process]::Start($probeInfo)
        if (-not $probe.WaitForExit(120000)) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $probe.Id /T /F | Out-Null
            throw 'New EXE startup check timed out. The installed EXE has not been changed.'
        }
        $probe.Refresh()
        if ($probe.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $report)) {
            throw 'New EXE could not start. The installed EXE has not been changed.'
        }
        $check = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $check.ok) { throw ('Startup check failed: ' + $check.error) }
    } finally { $env:QT_QPA_PLATFORM = $previousQpa }

    Log 'Installing the checked EXE...'
    # File.Replace is atomic and fails while an old bootloader still locks the
    # EXE. Retry instead of assuming that a fixed two-second delay is enough.
    $lastError = $null
    for ($attempt=0; $attempt -lt 120; $attempt++) {
        try {
            # NullString passes a real .NET null; PowerShell 5.1 can otherwise
            # convert $null into an empty backup filename.
            [System.IO.File]::Replace([string]$job.incoming,[string]$job.target,[System.Management.Automation.Language.NullString]::Value,$true)
            $swapped = $true
            break
        } catch {
            $lastError = $_
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $swapped) { throw $lastError }
    if ((Get-FileHash -LiteralPath $job.target -Algorithm SHA256).Hash -ne $job.sha256) {
        throw 'Installed EXE checksum mismatch.'
    }
    Log 'Starting PSSAQ in a new onefile environment...'
    $restartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $restartInfo.FileName = [string]$job.target
    $restartInfo.WorkingDirectory = [System.IO.Path]::GetDirectoryName([string]$job.target)
    $restartInfo.UseShellExecute = $false
    [void][System.Diagnostics.Process]::Start($restartInfo)
    Log 'Update complete. User settings, recordings and decoded text were kept.'
    # The staged EXE was consumed by File.Replace. Do not keep an EXE backup.
    Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
} catch {
    $failure = $_.Exception.Message
    Log ('UPDATE FAILED: ' + $failure)
    if ($swapped) { Log 'The checked new EXE is installed. Start it directly in Explorer.' }
    Log ('Details: ' + $log)
    Log 'Close this window, then start the installed PSSAQ.exe directly in Explorer.'
    Read-Host 'Press Enter to close'
    exit 1
}
