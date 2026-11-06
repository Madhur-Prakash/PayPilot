# Build PayPilot's APIMatic artefacts: the developer portal, SDKs and Context Plugin.
#
#   .\scripts\apimatic.ps1            spec + validate + portal + SDKs + plugin
#   .\scripts\apimatic.ps1 serve      live preview of the portal on http://localhost:23513
#   .\scripts\apimatic.ps1 portal     only the static portal (apimatic\portal)
#   .\scripts\apimatic.ps1 sdk        only the Python and TypeScript SDKs (apimatic\sdk)
#   .\scripts\apimatic.ps1 plugin     only the Context Plugin (apimatic\plugin)
#
# Needs the APIMatic CLI (npm i -g @apimatic/cli@2, Node 22.14+) and an APIMatic
# account. Either run `apimatic auth login` once, or put an API key in the root .env as
# APIMATIC_API_KEY (APIMatic dashboard -> Account -> API Keys). The key is never printed.
param([string]$Step = "all")
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Project = Join-Path $Root "apimatic"

if (-not (Get-Command apimatic -ErrorAction SilentlyContinue)) {
  Write-Error "APIMatic CLI not found. Install it with: npm i -g @apimatic/cli@2"
}

# Key from the environment, else from the root .env; blank means "use apimatic auth login".
$Key = $env:APIMATIC_API_KEY
$EnvFile = Join-Path $Root ".env"
if (-not $Key -and (Test-Path $EnvFile)) {
  $line = Select-String -Path $EnvFile -Pattern '^APIMATIC_API_KEY=' | Select-Object -Last 1
  if ($line) { $Key = ($line.Line -replace '^APIMATIC_API_KEY=', '').Trim('"', "'") }
}
$Auth = @()
if ($Key) { $Auth = @("--auth-key=$Key") }

function Invoke-Apimatic([string[]]$CliArgs) {
  & apimatic @CliArgs @Auth
  if ($LASTEXITCODE -ne 0) { throw "apimatic $($CliArgs[0..1] -join ' ') failed" }
}

function Update-Spec {
  Write-Host "==> Refreshing the OpenAPI spec from the FastAPI app"
  $py = Join-Path $Root "backend\.venv\Scripts\python.exe"
  if (-not (Test-Path $py)) { $py = "python" }
  Push-Location $Root
  try { & $py scripts/export_openapi.py } finally { Pop-Location }
}

function Build-Portal {
  Write-Host "==> Generating the static portal -> apimatic\portal"
  Invoke-Apimatic @("portal", "generate", "--input=$Project", "--destination=$(Join-Path $Project 'portal')", "--force")
}

function Build-Sdks {
  foreach ($lang in @("python", "typescript")) {
    Write-Host "==> Generating the $lang SDK -> apimatic\sdk\$lang"
    Invoke-Apimatic @("sdk", "generate", "--language=$lang", "--input=$Project", "--destination=$(Join-Path $Project "sdk\$lang")", "--force")
  }
}

function Build-Plugin {
  Write-Host "==> Generating the PayPilot Context Plugin -> apimatic\plugin"
  Invoke-Apimatic @("plugin", "generate", "--input=$Project", "--destination=$(Join-Path $Project 'plugin')", "--force")
}

switch ($Step) {
  "serve" { Invoke-Apimatic @("portal", "serve", "--input=$Project", "--open") }
  "spec" { Update-Spec }
  "validate" { Invoke-Apimatic @("api", "validate", "--input=$Project") }
  "portal" { Build-Portal }
  "sdk" { Build-Sdks }
  "plugin" { Build-Plugin }
  "all" {
    Update-Spec
    Invoke-Apimatic @("api", "validate", "--input=$Project")
    Build-Portal
    Build-Sdks
    Build-Plugin
    Write-Host "Done. Preview the portal with: .\scripts\apimatic.ps1 serve"
  }
  default { Write-Error "Unknown step '$Step' (all | serve | spec | validate | portal | sdk | plugin)" }
}
