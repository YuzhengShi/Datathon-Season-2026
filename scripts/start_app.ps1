<#
.SYNOPSIS
  Start Funding Navigator for a demo: prepare the database from the stored snapshots (nothing is downloaded) and open the browser.
.EXAMPLE
  .\scripts\start_app.ps1                 # http://127.0.0.1:8000/
  .\scripts\start_app.ps1 -Port 8080      # if Windows refuses the port (WinError 10013)
  .\scripts\start_app.ps1 -Rebuild        # rebuild the database from the stored snapshots
#>
param([int]$Port = 8000, [switch]$Rebuild, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw 'Create the environment first: python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.lock; .venv\Scripts\python -m pip install --no-deps -e .' }
$env:DATA_MODE = 'live'
$env:PYTHONUTF8 = '1'
$db = Join-Path $root 'data\navigator.db'
if ($Rebuild -or -not (Test-Path $db)) {
    Write-Host 'Preparing the database from the stored snapshots (this reuses saved pages; exit code 3 means a source such as UBC is missing, which is expected)...'
    & $py -m navigator.cli pipeline --mode live --limit 200 --max-pages 200 --resume | Out-Null
}
$url = "http://127.0.0.1:$Port/"
if (-not $NoBrowser) { Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 3; Start-Process $u } -ArgumentList $url | Out-Null }
Write-Host "Funding Navigator is starting at $url  (press Ctrl+C to stop)"
& $py -m navigator.cli serve --mode live --host 127.0.0.1 --port $Port
