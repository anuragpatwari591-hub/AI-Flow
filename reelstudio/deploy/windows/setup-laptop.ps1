<#
.SYNOPSIS
  Zero-cost Windows 11 laptop setup for Reel Studio (Docker Desktop + free HTTPS tunnel). Re-runnable.
.DESCRIPTION
  Checks Docker Desktop / WSL 2, creates .env (secrets generated locally, never printed), starts db + api + worker + gate +
  a free tunnel, verifies health and that ONLY the Instagram-required paths are public, then guides Instagram OAuth.
  It never publishes, never enables publishing, never handles your Instagram password, never prints secrets.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\deploy\windows\setup-laptop.ps1
.EXAMPLE
  .\deploy\windows\setup-laptop.ps1 -Tunnel Ngrok     # stable URL; needs a free ngrok account (authtoken + free domain)
#>
#Requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('Auto', 'Quick', 'Ngrok')] [string]$Tunnel = 'Auto',
    [switch]$InstallDocker,   # offer to install Docker Desktop with winget (asks first)
    [switch]$CopyToken,       # copy the dashboard token to the clipboard (never printed)
    [switch]$Status,          # only run the read-only readiness report
    [switch]$Stop             # stop the stack (data volumes are kept)
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $Root
$ComposeFile = 'docker-compose.laptop.yml'
$EnvFile = Join-Path $Root '.env'
$TunnelFile = Join-Path $Root '.env.tunnel'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Stop-Next([string]$Why, [string]$Next) {
    Write-Host ''
    Write-Host "BLOCKED: $Why" -ForegroundColor Red
    Write-Host "NEXT: $Next" -ForegroundColor Yellow
    exit 1
}
function Info([string]$m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Dc { & docker compose -f $ComposeFile @args }

# ---------------------------------------------------------------- env file helpers (no secret is ever written to the console)
function New-RandomBytes([int]$n) {
    $b = New-Object byte[] $n
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($b)
    $rng.Dispose()
    return , $b
}
function New-FernetKey { [Convert]::ToBase64String((New-RandomBytes 32)).Replace('+', '-').Replace('/', '_') }
function New-UrlToken { [Convert]::ToBase64String((New-RandomBytes 36)).Replace('+', '').Replace('/', '').Replace('=', '') }
function New-HexPassword { -join ((New-RandomBytes 24) | ForEach-Object { $_.ToString('x2') }) }

function Read-EnvMap([string]$Path) {
    $map = @{}
    if (Test-Path $Path) {
        foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
            if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') { $map[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'") }
        }
    }
    return $map
}
# Fill KEY only when absent/empty (never overwrite a credential) unless -Force (used for derived, non-secret values).
function Set-EnvValue([string]$Path, [string]$Key, [string]$Value, [switch]$Force) {
    $lines = @()
    if (Test-Path $Path) { $lines = @([System.IO.File]::ReadAllLines($Path)) }
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$([regex]::Escape($Key))\s*=(.*)$") {
            $found = $true
            $current = $Matches[1].Trim().Trim('"').Trim("'")
            if ($Force -or $current -eq '') { $lines[$i] = "$Key=$Value" }
        }
    }
    if (-not $found) { $lines += "$Key=$Value" }
    [System.IO.File]::WriteAllText($Path, (($lines -join "`n") + "`n"), $Utf8NoBom)
    & icacls.exe $Path /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
}
function Read-SecretPlain([string]$Prompt) {
    $s = Read-Host -Prompt $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
function Test-SafeValue([string]$v) { return ($v -match '^[A-Za-z0-9._:-]+$') }

# ---------------------------------------------------------------- -Stop / -Status
if ($Stop) {
    Dc --profile quick --profile ngrok down
    Write-Host 'Stopped. Your data is kept in Docker volumes.'
    exit 0
}

# ---------------------------------------------------------------- 1. prerequisites
Info 'Checking Windows, Docker Desktop and WSL 2'
if ([Environment]::OSVersion.Version.Build -lt 19041) {
    Stop-Next 'Windows is too old for WSL 2.' 'Update Windows (Windows 11 recommended), then re-run this script.'
}
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCmd) {
    if ($InstallDocker -and (Get-Command winget -ErrorAction SilentlyContinue)) {
        $ok = Read-Host 'Install Docker Desktop now with winget? It is free for personal use. (y/N)'
        if ($ok -eq 'y') {
            & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
            Stop-Next 'Docker Desktop was just installed.' 'Restart Windows if asked, start Docker Desktop, accept its terms and wait for "Engine running", then re-run this script.'
        }
    }
    Stop-Next 'Docker Desktop is not installed.' 'Re-run with -InstallDocker (or install Docker Desktop from docker.com/products/docker-desktop), restart, start Docker Desktop, then re-run this script.'
}
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-Next 'Docker Desktop is installed but its engine is not running.' 'Start Docker Desktop from the Start menu, wait until it says "Engine running", then re-run this script.'
}
$kernel = (& docker info --format '{{.KernelVersion}}') | Out-String
if ($kernel -notmatch 'WSL2|microsoft') {
    Stop-Next 'Docker is not using the WSL 2 backend.' 'Docker Desktop -> Settings -> General -> tick "Use the WSL 2 based engine" -> Apply & restart, then re-run this script.'
}
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Stop-Next 'Docker Compose v2 is missing.' 'Update Docker Desktop to the latest version, then re-run this script.' }
Write-Host 'Docker Desktop (WSL 2) and Compose are OK.'

if ($Status) {
    Dc exec -T api reelstudio setup --check
    exit $LASTEXITCODE
}

# ---------------------------------------------------------------- 2. secrets (.env)
Info 'Preparing .env (secrets are generated locally and never shown)'
$envMap = Read-EnvMap $EnvFile
if (-not $envMap.ContainsKey('RS_SECRET_KEY') -or $envMap['RS_SECRET_KEY'] -eq '') { Set-EnvValue $EnvFile 'RS_SECRET_KEY' (New-FernetKey) }
if (-not $envMap.ContainsKey('RS_DASHBOARD_TOKEN') -or $envMap['RS_DASHBOARD_TOKEN'] -eq '') { Set-EnvValue $EnvFile 'RS_DASHBOARD_TOKEN' (New-UrlToken) }
if (-not $envMap.ContainsKey('POSTGRES_PASSWORD') -or $envMap['POSTGRES_PASSWORD'] -eq '') { Set-EnvValue $EnvFile 'POSTGRES_PASSWORD' (New-HexPassword) }
Set-EnvValue $EnvFile 'RS_AI_PROVIDER' 'local'
$envMap = Read-EnvMap $EnvFile
if (-not $envMap.ContainsKey('RS_META_APP_ID') -or $envMap['RS_META_APP_ID'] -eq '') {
    $id = Read-Host 'Instagram app ID (Meta dashboard > GenZ Reel Studio > Instagram > API setup with Instagram login)'
    if (-not (Test-SafeValue $id)) { Stop-Next 'The app ID is empty or has unexpected characters.' 'Copy the Instagram app ID from Meta (API setup with Instagram login) and re-run.' }
    Set-EnvValue $EnvFile 'RS_META_APP_ID' $id
}
if (-not $envMap.ContainsKey('RS_META_APP_SECRET') -or $envMap['RS_META_APP_SECRET'] -eq '') {
    $sec = Read-SecretPlain 'Instagram app secret (typing is hidden)'
    if (-not (Test-SafeValue $sec)) { Stop-Next 'The app secret is empty or has unexpected characters.' 'Copy the Instagram app secret from the same Meta page and re-run.' }
    Set-EnvValue $EnvFile 'RS_META_APP_SECRET' $sec
    $sec = $null
}
if ($CopyToken) { Set-Clipboard -Value (Read-EnvMap $EnvFile)['RS_DASHBOARD_TOKEN']; Write-Host 'Dashboard token copied to the clipboard (clear it after use: Win+V).' }

# ---------------------------------------------------------------- 3. choose the tunnel
$envMap = Read-EnvMap $EnvFile
$tunnelMap = Read-EnvMap $TunnelFile
$hasNgrok = ($envMap.ContainsKey('NGROK_DOMAIN') -and $envMap['NGROK_DOMAIN'] -ne '' -and $tunnelMap.ContainsKey('NGROK_AUTHTOKEN') -and $tunnelMap['NGROK_AUTHTOKEN'] -ne '')
$mode = $Tunnel
if ($mode -eq 'Auto') { if ($hasNgrok) { $mode = 'Ngrok' } else { $mode = 'Quick' } }
if ($mode -eq 'Ngrok' -and -not $hasNgrok) {
    Write-Host 'ngrok setup: ngrok.com -> sign up (free) -> Your Authtoken, and Domains -> your free domain (e.g. name.ngrok-free.app).'
    $dom = Read-Host 'Your ngrok domain (no https://)'
    if (-not (Test-SafeValue $dom)) { Stop-Next 'The ngrok domain is empty or invalid.' 'Copy your domain from dashboard.ngrok.com/domains and re-run with -Tunnel Ngrok.' }
    $tok = Read-SecretPlain 'ngrok authtoken (typing is hidden)'
    if (-not (Test-SafeValue $tok)) { Stop-Next 'The authtoken is empty or invalid.' 'Copy it from dashboard.ngrok.com/get-started/your-authtoken and re-run with -Tunnel Ngrok.' }
    Set-EnvValue $EnvFile 'NGROK_DOMAIN' $dom
    Set-EnvValue $TunnelFile 'NGROK_AUTHTOKEN' $tok
    $tok = $null
}
if ($mode -eq 'Ngrok') {
    $dom = (Read-EnvMap $EnvFile)['NGROK_DOMAIN']
    Set-EnvValue $EnvFile 'RS_PUBLIC_URL' "https://$dom" -Force
} elseif (-not (Read-EnvMap $EnvFile).ContainsKey('RS_PUBLIC_URL') -or (Read-EnvMap $EnvFile)['RS_PUBLIC_URL'] -eq '') {
    Set-EnvValue $EnvFile 'RS_PUBLIC_URL' 'https://pending.invalid' -Force   # replaced once the quick tunnel reports its URL
}
$profile = $mode.ToLower()

# ---------------------------------------------------------------- 4. start the stack
Info "Starting db, api, worker, gate and the '$profile' tunnel (first build takes several minutes)"
Dc --profile $profile up -d --build --wait
if ($LASTEXITCODE -ne 0) {
    Stop-Next 'The stack did not become healthy.' 'Run: docker compose -f docker-compose.laptop.yml logs --tail 80 api   and fix the error shown (no secrets are logged), then re-run this script.'
}

if ($mode -eq 'Quick') {
    Info 'Waiting for the free tunnel to report its HTTPS address'
    $publicUrl = $null
    for ($i = 0; $i -lt 40 -and -not $publicUrl; $i++) {
        $log = (Dc logs --no-log-prefix cloudflared 2>&1) | Out-String
        foreach ($m in [regex]::Matches($log, 'https://[a-z0-9-]+\.trycloudflare\.com')) {
            if ($m.Value -ne 'https://api.trycloudflare.com') { $publicUrl = $m.Value; break }   # api.* is cloudflared's own control endpoint
        }
        if (-not $publicUrl) { Start-Sleep -Seconds 3 }
    }
    if (-not $publicUrl) { Stop-Next 'The Cloudflare quick tunnel did not report a URL.' 'Check your internet connection / firewall, then re-run this script.' }
    if ((Read-EnvMap $EnvFile)['RS_PUBLIC_URL'] -ne $publicUrl) {
        Set-EnvValue $EnvFile 'RS_PUBLIC_URL' $publicUrl -Force
        Dc --profile $profile up -d --wait api worker   # recreate with the new public URL
    }
}
$publicUrl = (Read-EnvMap $EnvFile)['RS_PUBLIC_URL']

# ---------------------------------------------------------------- 5. verify health, rendering deps and exposure
Info 'Verifying health'
try { $local = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/healthz' -TimeoutSec 15 } catch { Stop-Next 'The API did not answer on http://127.0.0.1:8000/healthz.' 'Run: docker compose -f docker-compose.laptop.yml logs --tail 80 api' }
if (-not $local.ok) { Stop-Next 'The API reported unhealthy.' 'Run: docker compose -f docker-compose.laptop.yml logs --tail 80 api' }
if (-not $local.ffmpeg) { Stop-Next 'FFmpeg is missing inside the container (video rendering would fail).' 'Rebuild the image: docker compose -f docker-compose.laptop.yml build --no-cache api   then re-run this script.' }
Write-Host 'Local API healthy; FFmpeg present.'

$reachable = $false
for ($i = 0; $i -lt 30 -and -not $reachable; $i++) {
    try { $r = Invoke-RestMethod -Uri "$publicUrl/healthz" -TimeoutSec 10; if ($r.ok) { $reachable = $true } } catch { Start-Sleep -Seconds 4 }
}
if (-not $reachable) { Stop-Next "The public HTTPS address ($publicUrl) is not reachable yet." 'Wait a minute and re-run this script (new tunnel addresses can take up to a minute to resolve).' }
Write-Host "Public HTTPS address reachable: $publicUrl"
$exposed = $false
try { $resp = Invoke-WebRequest -Uri "$publicUrl/" -UseBasicParsing -TimeoutSec 10; if ($resp.StatusCode -eq 200) { $exposed = $true } } catch { }
if ($exposed) { Stop-Next 'The dashboard is publicly reachable through the tunnel (the gate is not filtering).' 'Run: docker compose -f docker-compose.laptop.yml down   and report this; do not continue.' }
Write-Host 'Gate check passed: the dashboard and /api are NOT reachable from the internet.'

# ---------------------------------------------------------------- 6. Meta callback + Instagram OAuth (you authorize; nothing is published)
$callback = "$publicUrl/api/instagram/callback"
$accountOk = $false
$check = (Dc exec -T api reelstudio setup --check) | Out-String
if ($check -match '\[OK\s*\] @\S+ required permissions') { $accountOk = $true }
if (-not $accountOk) {
    Write-Host ''
    Write-Host 'META CALLBACK (add exactly this, then Save):' -ForegroundColor Cyan
    Write-Host "  $callback" -ForegroundColor White
    Write-Host '  Meta for Developers > GenZ Reel Studio > Instagram > API setup with Instagram login > Business login settings > OAuth redirect URIs'
    if ($mode -eq 'Quick') { Write-Host '  (Quick tunnel URLs change each start: only needed while connecting; Instagram stays connected afterwards.)' -ForegroundColor DarkYellow }
    [void](Read-Host 'Press Enter once the redirect URI is saved in Meta')
    $url = ((Dc exec -T api reelstudio connect-url) | Out-String).Trim()
    if ($url -notmatch '^https://www\.instagram\.com/oauth/authorize') { Stop-Next 'Could not build the Instagram authorization URL.' 'Run: docker compose -f docker-compose.laptop.yml exec api reelstudio setup --check   and fix the first FAIL shown.' }
    Info 'Opening Instagram authorization. Log in and approve the permissions yourself; setup waits up to 5 minutes.'
    Start-Process $url
    Dc exec -T api reelstudio setup --wait 300 --no-browser --non-interactive
} else {
    Dc exec -T api reelstudio setup --non-interactive --no-browser
}
$code = $LASTEXITCODE
Write-Host ''
if ($code -eq 0) {
    Write-Host 'READY. Dashboard: http://localhost:8000  (every post still needs your approval)' -ForegroundColor Green
} else {
    Write-Host 'Dashboard (local only): http://localhost:8000   (token: open .env in Notepad, or re-run with -CopyToken)' -ForegroundColor Cyan
}
exit $code
