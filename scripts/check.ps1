# PayPilot - environment check for Windows PowerShell (5.1+). Read-only.
# Verifies Python, Node, npm, git, Docker, the .env file and installed
# dependencies, and reports the PayPal / LLM mode. Same as `make check`.
#
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if ($null -eq $python) {
    Write-Host "Python 3.11+ is required: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

& $python.Source scripts\tasks.py check
exit $LASTEXITCODE
