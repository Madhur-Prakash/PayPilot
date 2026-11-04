# PayPilot - run the development stack on Windows PowerShell (5.1+).
# Starts Postgres via Docker when available, then the backend (:8000) and the
# frontend (:3000). Ctrl-C stops both. Same as `make dev`.
#
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 [-Port 8000] [-WebPort 3000]
param([int]$Port = 8000, [int]$WebPort = 3000)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if ($null -eq $python) {
    Write-Host "Python 3.11+ is required: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

& $python.Source scripts\tasks.py dev --port $Port --web-port $WebPort
exit $LASTEXITCODE
