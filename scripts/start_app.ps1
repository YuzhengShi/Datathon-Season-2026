<#
.SYNOPSIS
  Start Funding Navigator: build the database if needed, then serve the app and open the browser.
  With the saved source pages (data\raw) it rebuilds and re-verifies everything without downloading; in a fresh clone it loads the prepared
  dataset data\awards.jsonl (verified when it was built).
.EXAMPLE
  .\scripts\start_app.ps1                 # http://127.0.0.1:8000/
  .\scripts\start_app.ps1 -Port 8080      # if Windows refuses the port (WinError 10013)
  .\scripts\start_app.ps1 -Rebuild        # build the database again
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
    if (Test-Path $db) { Remove-Item $db -Force }
    & $py -m navigator.cli db upgrade --mode live | Out-Null
    $saved = @(Get-ChildItem (Join-Path $root 'data\raw') -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne '.gitkeep' }).Count
    if ($saved -ge 5) {
        Write-Host "Rebuilding from $saved saved pages (nothing is downloaded; exit code 3 only means a source such as UBC is missing)..."
        & $py -m navigator.cli pipeline --mode live --limit 200 --max-pages 200 --resume | Out-Null
    } else {
        Write-Host 'Loading the prepared dataset data/awards.jsonl ...'
        & $py -m navigator.cli import-data --input data/awards.jsonl --artifact-root data --mode live --trust-export | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Could not load data/awards.jsonl' }
    }
    & $py -m navigator.cli report --mode live | Out-Null
}
$url = "http://127.0.0.1:$Port/"
if (-not $NoBrowser) { Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 3; Start-Process $u } -ArgumentList $url | Out-Null }
Write-Host "Funding Navigator is starting at $url  (press Ctrl+C to stop)"
& $py -m navigator.cli serve --mode live --host 127.0.0.1 --port $Port
