#Requires -Version 5.1
<#
.SYNOPSIS
    Commander AI Lab - Fresh Installer
    Downloads the project from GitHub and sets up the environment.

.USAGE
    powershell -ExecutionPolicy Bypass -File install-commander-ai-lab.ps1

.PARAMETERS
    -TargetDir   Installation directory (default: D:\ForgeCommander\commander-ai-lab)
    -Branch      Git branch to install from (default: main)
    -SkipPython  Skip Python dependency installation
    -SkipJava    Skip Java 17 check
#>
[CmdletBinding()]
param(
    [string]$TargetDir = 'D:\ForgeCommander\commander-ai-lab',
    [string]$Branch    = 'main',
    [switch]$SkipPython,
    [switch]$SkipJava
)

$ErrorActionPreference = 'Stop'
$RepoUrl = 'https://github.com/KoalaTrapLord/commander-ai-lab.git'

function Write-Step([string]$msg) {
    Write-Host "`n>>> $msg" -ForegroundColor Cyan
}
function Write-OK([string]$msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
}
function Write-Warn([string]$msg) {
    Write-Host "  [WARN] $msg" -ForegroundColor Yellow
}
function Write-Fail([string]$msg) {
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
}

Write-Host ''
Write-Host '  =================================================' -ForegroundColor Cyan
Write-Host '   Commander AI Lab - Fresh Installer'              -ForegroundColor Cyan
Write-Host '   v28: Coach Chat + Analytics + Export-to-Sim'    -ForegroundColor Cyan
Write-Host '  =================================================' -ForegroundColor Cyan
Write-Host ''

# ── 1. Check prerequisites ────────────────────────────────────
Write-Step 'Checking prerequisites'

# Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Fail 'Git not found. Install from https://git-scm.com/download/win and re-run.'
    exit 1
}
Write-OK 'Git found'

# Python
if (-not $SkipPython) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Fail 'Python not found. Install Python 3.10+ from https://python.org and re-run.'
        exit 1
    }
    $pyVer = python --version 2>&1
    Write-OK "Python: $pyVer"
}

# Java 17 (optional — only needed for batch sim)
if (-not $SkipJava) {
    $javaFound = Get-Command java -ErrorAction SilentlyContinue
    if ($javaFound) {
        $javaVer = java -version 2>&1 | Select-Object -First 1
        Write-OK "Java: $javaVer"
    } else {
        Write-Warn 'Java not found. Batch simulation will be disabled. Install Java 17 from https://adoptium.net'
    }
}

# ── 2. Clone or update repository ────────────────────────────
Write-Step 'Setting up repository'

if (Test-Path (Join-Path $TargetDir '.git')) {
    Write-Host "  Repository exists at $TargetDir — pulling latest changes..."
    Push-Location $TargetDir
    try {
        git fetch origin
        git checkout $Branch
        git pull origin $Branch
        Write-OK 'Repository updated'
    } finally {
        Pop-Location
    }
} else {
    if (Test-Path $TargetDir) {
        $files = Get-ChildItem $TargetDir -ErrorAction SilentlyContinue
        if ($files) {
            Write-Fail "Target directory '$TargetDir' exists and is not empty. Remove it or choose a different -TargetDir."
            exit 1
        }
    }
    Write-Host "  Cloning $RepoUrl into $TargetDir..."
    git clone --branch $Branch --depth 1 $RepoUrl $TargetDir
    Write-OK "Repository cloned to $TargetDir"
}

# ── 3. Install Python dependencies ───────────────────────────
if (-not $SkipPython) {
    Write-Step 'Installing Python dependencies'
    Push-Location $TargetDir
    try {
        if (Test-Path 'pyproject.toml') {
            python -m pip install --upgrade pip
            python -m pip install -e ".[dev]"
            Write-OK 'Python dependencies installed (pyproject.toml)'
        } elseif (Test-Path 'requirements.txt') {
            python -m pip install --upgrade pip
            python -m pip install -r requirements.txt
            Write-OK 'Python dependencies installed (requirements.txt)'
        } else {
            Write-Warn 'No pyproject.toml or requirements.txt found. Skipping pip install.'
        }
    } finally {
        Pop-Location
    }
}

# ── 4. Create .env if missing ────────────────────────────────
Write-Step 'Checking environment config'
$envFile = Join-Path $TargetDir '.env'
if (-not (Test-Path $envFile)) {
    $envExample = Join-Path $TargetDir '.env.example'
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-OK '.env created from .env.example (edit it to add your API keys)'
    } else {
        @'
# Commander AI Lab environment variables
# Uncomment and fill in the values you need:

# XIMILAR_API_KEY=your_ximilar_key_here
# PPLX_API_KEY=your_perplexity_key_here
# FORGE_JAR=C:\Path\To\forge-gui-desktop.jar
# FORGE_DIR=C:\Path\To\Forge
# LAB_PORT=8080
'@ | Set-Content $envFile
        Write-OK '.env created with defaults (edit to add your API keys)'
    }
} else {
    Write-OK '.env already exists'
}

# ── 5. Summary ────────────────────────────────────────────────
Write-Host ''
Write-Host '  =================================================' -ForegroundColor Green
Write-Host '   Installation complete!' -ForegroundColor Green
Write-Host '  =================================================' -ForegroundColor Green
Write-Host ''
Write-Host "  Install path : $TargetDir" -ForegroundColor White
Write-Host '  Start server : python lab_api.py' -ForegroundColor White
Write-Host '  API docs     : http://localhost:8080/docs' -ForegroundColor White
Write-Host '  Web UI       : http://localhost:8080/' -ForegroundColor White
Write-Host ''
Write-Host '  Edit .env to configure API keys before starting.' -ForegroundColor Yellow
Write-Host ''
