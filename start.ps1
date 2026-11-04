#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 8501,
    [switch]$InstallDependencies,
    [ValidateRange(1, 300)][int]$StartupTimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$app = Join-Path $root 'app.py'
$runtime = Join-Path $root '.run'
$statePath = Join-Path $runtime 'audio-idp.json'
$stdout = Join-Path $runtime 'stdout.log'
$stderr = Join-Path $runtime 'stderr.log'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null

# Serialize start/stop operations, including environment setup.
$lock = [System.IO.File]::Open((Join-Path $runtime 'lifecycle.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $existing = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
        if ($null -ne $existing -and $existing.StartTime.ToUniversalTime().Ticks.ToString() -eq $state.startTimeUtcTicks) {
            if ($state.app -ne $app -or $existing.Path -ne $python) {
                throw 'The recorded process does not match this application. Check .run/audio-idp.json.'
            }
            Write-Host "Audio IDP is already running at http://127.0.0.1:$($state.port) (PID $($state.pid))."
            return
        }
        Remove-Item -LiteralPath $statePath
    }

    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try { $listener.Start() }
    catch { throw "Port $Port is unavailable. Stop its owner or use .\start.ps1 -Port 8502." }
    finally { $listener.Stop() }

    $createdEnvironment = $false
    if (-not (Test-Path -LiteralPath $python)) {
        if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
            throw 'Install Python 3.13 (64-bit) with the Windows Python launcher, then retry.'
        }
        Write-Host 'Creating the Python 3.13 virtual environment...'
        & py.exe -3.13 -m venv (Join-Path $root '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv. Install Python 3.13 (64-bit), then retry.' }
        $createdEnvironment = $true
    }

    & $python -c "import sys; sys.exit(sys.version_info[:2] != (3, 13))"
    if ($LASTEXITCODE -ne 0) {
        throw 'The existing .venv must use Python 3.13. Recreate it with py -3.13 -m venv .venv before starting.'
    }

    # Read distribution metadata without loading models or contacting AWS.
    & $python -c "import importlib.metadata as m, sys; names={d.metadata['Name'].lower() for d in m.distributions()}; sys.exit(not all(n in names for n in ('streamlit', 'boto3', 'faster-whisper', 'av', 'numpy', 'requests')))"
    $dependenciesMissing = $LASTEXITCODE -ne 0
    if ($createdEnvironment -or $dependenciesMissing -or $InstallDependencies) {
        Write-Host 'Installing application dependencies...'
        & $python -m pip install -r (Join-Path $root 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the pip output and retry start.ps1.' }
    }

    # Start-Process joins Windows arguments; quote the absolute app path explicitly.
    $arguments = '-m streamlit run "{0}" --server.address 127.0.0.1 --server.port {1} --server.maxUploadSize 50 --server.headless true --browser.gatherUsageStats false' -f $app, $Port
    $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    try {
        [ordered]@{
            pid = $process.Id
            startTimeUtcTicks = $process.StartTime.ToUniversalTime().Ticks.ToString()
            port = $Port
            app = $app
        } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        $url = "http://127.0.0.1:$Port"
        $deadline = [DateTime]::UtcNow.AddSeconds($StartupTimeoutSeconds)
        while ([DateTime]::UtcNow -lt $deadline) {
            $process.Refresh()
            if ($process.HasExited) { throw "Streamlit exited with code $($process.ExitCode)." }
            try {
                $response = Invoke-WebRequest -Uri "$url/_stcore/health" -UseBasicParsing -TimeoutSec 2
                if ($response.StatusCode -eq 200) {
                    $process.Refresh()
                    if (-not $process.HasExited) {
                        Write-Host "Audio IDP is ready at $url (PID $($process.Id))."
                        Write-Host "Logs: $stdout and $stderr"
                        Write-Host 'Stop with .\stop.ps1. Download your results before stopping.'
                        return
                    }
                }
            }
            catch { Write-Verbose $_.Exception.Message }
            Start-Sleep -Milliseconds 500
        }
        throw "Streamlit did not become ready within $StartupTimeoutSeconds seconds."
    }
    catch {
        $startupError = $_.Exception.Message
        if (-not $process.HasExited) {
            & taskkill.exe /PID $process.Id /T /F
            if ($LASTEXITCODE -ne 0) {
                throw "$startupError Automatic cleanup failed; process information was retained. Run stop.ps1. Check $stdout and $stderr."
            }
        }
        Remove-Item -LiteralPath $statePath -ErrorAction SilentlyContinue
        throw "$startupError Check $stdout and $stderr."
    }
}
finally { $lock.Dispose() }
