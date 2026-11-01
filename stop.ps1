#Requires -Version 5.1
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '.run'
$statePath = Join-Path $runtime 'audio-idp.json'
if (-not (Test-Path -LiteralPath $runtime)) {
    Write-Host 'Audio IDP is not running through start.ps1.'
    return
}
$lock = [System.IO.File]::Open((Join-Path $runtime 'lifecycle.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-Host 'Audio IDP is not running through start.ps1.'
        return
    }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if ($null -eq $process -or $process.StartTime.ToUniversalTime().Ticks.ToString() -ne $state.startTimeUtcTicks) {
        Remove-Item -LiteralPath $statePath
        Write-Host 'Audio IDP has already stopped. Removed stale process information.'
        return
    }

    # Check the interpreter and creation time before stopping the process tree.
    $app = Join-Path $PSScriptRoot 'app.py'
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if ($state.app -ne $app -or $process.Path -ne $python) {
        throw 'The recorded process does not match this application. No process was stopped.'
    }
    # Windows virtual-environment launchers can have a child Python process.
    & taskkill.exe /PID $process.Id /T /F
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the application process tree. Retry stop.ps1.' }
    if (-not $process.WaitForExit(10000)) { throw 'The application did not exit within 10 seconds. Retry stop.ps1.' }
    Remove-Item -LiteralPath $statePath
    Write-Host 'Audio IDP stopped. Logs remain in .run. Unsaved Streamlit session data is discarded.'
}
finally { $lock.Dispose() }
