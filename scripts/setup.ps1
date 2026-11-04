# PayPilot - first-time setup for Windows PowerShell (5.1+).
# Same as `make init`: checks tools, creates .env only if missing, installs
# dependencies, and prepares the database when Docker is running.
# Never overwrites .env and never deletes data.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-SkipDb]
param([switch]$SkipDb)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if ($null -eq $python) {
    Write-Host "Python 3.11+ is required: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

$taskArgs = @("scripts\tasks.py", "init")
if ($SkipDb) { $taskArgs += "--skip-db" }
& $python.Source @taskArgs
exit $LASTEXITCODE
