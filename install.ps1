# install.ps1 — Install cloding on Windows
#
# Usage:
#   irm https://raw.githubusercontent.com/claudlos/cloding/master/install.ps1 | iex

$ErrorActionPreference = "Stop"

$repo = "claudlos/cloding"
$binaryName = "cloding.exe"
$assetName = "cloding-win-x64.exe"

# Default install dir: ~/.cloding/bin (no admin needed)
$installDir = Join-Path $env:USERPROFILE ".cloding\bin"

# ── Get latest release ──
Write-Host "Fetching latest release..."
try {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -UseBasicParsing
    $tag = $release.tag_name -replace '^v', ''
} catch {
    Write-Host "Error: Could not fetch latest release." -ForegroundColor Red
    Write-Host "Check: https://github.com/$repo/releases"
    exit 1
}

$downloadUrl = "https://github.com/$repo/releases/download/v$tag/$assetName"

Write-Host "Downloading cloding v$tag (windows/x64)..."
Write-Host "  $downloadUrl"

# ── Ensure install directory exists ──
if (-not (Test-Path $installDir)) {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
}

$outPath = Join-Path $installDir $binaryName

# ── Download ──
try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $outPath -UseBasicParsing
} catch {
    Write-Host "Error: Download failed." -ForegroundColor Red
    Write-Host "Check releases at: https://github.com/$repo/releases"
    exit 1
}

# ── Add to user PATH if not already there ──
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$installDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$installDir", "User")
    Write-Host ""
    Write-Host "Added $installDir to your PATH." -ForegroundColor Green
    Write-Host "Restart your terminal for PATH changes to take effect."
}

Write-Host ""
Write-Host "cloding v$tag installed to $outPath" -ForegroundColor Green
Write-Host ""
Write-Host "Get started:"
Write-Host "  `$env:OPENROUTER_API_KEY = 'sk-or-v1-...'"
Write-Host "  cloding"
Write-Host "  cloding setup   # Install all CLI tools (Claude, Gemini, Codex, etc.)"
Write-Host ""
