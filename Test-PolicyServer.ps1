<#
.SYNOPSIS
    Smoke-tests the Commander AI Lab policy server from PowerShell.
    Checks: server reachable → /api/policy/health → /api/policy/decide.
    Prints a plain-English pass/fail for every step so you know
    exactly where the pipeline is broken.

.USAGE
    # From repo root (server already running in another window):
    .\Test-PolicyServer.ps1

    # Custom host/port:
    .\Test-PolicyServer.ps1 -BaseUrl http://localhost:9000

    # Pretty-print the full decide response:
    .\Test-PolicyServer.ps1 -Verbose
#>
param(
    [string]$BaseUrl = "http://localhost:8000",
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

# ─── helpers ────────────────────────────────────────────────────────────────

function Write-Pass  { param([string]$msg) Write-Host "  [PASS] $msg" -ForegroundColor Green  }
function Write-Fail  { param([string]$msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red    }
function Write-Info  { param([string]$msg) Write-Host "  [INFO] $msg" -ForegroundColor Cyan   }
function Write-Warn  { param([string]$msg) Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Step  { param([string]$msg) Write-Host "`n── $msg" -ForegroundColor White      }

$allPassed = $true

function Invoke-Step {
    param(
        [string]   $Name,
        [scriptblock] $Block
    )
    Write-Step $Name
    try {
        & $Block
    } catch {
        Write-Fail $_.Exception.Message
        $script:allPassed = $false
    }
}

# ─── Step 1: Server reachable ────────────────────────────────────────────────

Invoke-Step "Step 1 — Server reachable at $BaseUrl" {
    $resp = Invoke-WebRequest -Uri "$BaseUrl/docs" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
    if ($resp -and $resp.StatusCode -eq 200) {
        Write-Pass "FastAPI server is up (GET /docs → 200)"
    } else {
        # /docs might be disabled; try root
        $resp2 = Invoke-WebRequest -Uri "$BaseUrl/" -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($resp2 -and $resp2.StatusCode -lt 500) {
            Write-Pass "FastAPI server is up (GET / → $($resp2.StatusCode))"
        } else {
            throw "Cannot reach $BaseUrl — is lab_api.py / uvicorn running?"
        }
    }
}

# ─── Step 2: /api/policy/health ─────────────────────────────────────────────

$modelLoaded = $false

Invoke-Step "Step 2 — GET $BaseUrl/api/policy/health" {
    $resp = Invoke-RestMethod -Uri "$BaseUrl/api/policy/health" -Method Get -TimeoutSec 10

    if ($Verbose) { $resp | ConvertTo-Json -Depth 5 | Write-Host }

    if ($resp.ready -eq $true) {
        Write-Pass "Model is loaded and ready  (ready=true)"
        $script:modelLoaded = $true
    } elseif ($resp.status -eq "degraded") {
        Write-Fail "Health endpoint returned status=degraded / ready=false"
        Write-Warn "  → The policy model is NOT loaded."
        Write-Warn "  → Start the server with --load-policy or call POST /api/ml/load_model first."
        Write-Warn "  → Check that models/ contains a valid checkpoint (.pt file)."
        $script:allPassed = $false
    } else {
        Write-Warn "Unexpected health response — dumping:"
        $resp | ConvertTo-Json -Depth 5 | Write-Host
        $script:allPassed = $false
    }
}

# ─── Step 3: /api/policy/decide (synthetic snapshot) ─────────────────────────

Invoke-Step "Step 3 — POST $BaseUrl/api/policy/decide  (synthetic 4-player snapshot)" {

    if (-not $script:modelLoaded) {
        Write-Warn "Skipping /decide test because model is not loaded (Step 2 failed)."
        Write-Warn "Fix Step 2 first, then re-run this script."
        return
    }

    # Minimal but schema-valid DecideRequest.
    # Matches the PlayerZoneState + DecideRequest pydantic models in routes/policy.py.
    $body = @{
        game_id        = "ps1-smoke-test"
        turn           = 3
        phase          = "MAIN1"
        active_player  = 0
        playstyle      = "midrange"
        temperature    = 1.0
        greedy         = $false
        players        = @(
            @{
                seat              = 0
                name              = "TestPlayer0"
                life              = 40
                manaAvailable     = 3
                landCount         = 3
                creaturesOnField  = 1
                totalPowerOnBoard = 2
                hand              = @("Cultivate", "Solemn Simulacrum", "Sol Ring")
                battlefield       = @("Forest", "Forest", "Forest", "Birds of Paradise")
                graveyard         = @()
                commandZone       = @("Atraxa, Praetors' Voice")
            },
            @{
                seat              = 1
                name              = "TestPlayer1"
                life              = 38
                manaAvailable     = 2
                landCount         = 2
                creaturesOnField  = 0
                totalPowerOnBoard = 0
                hand              = @()
                handCount         = 4
                battlefield       = @("Island", "Swamp")
                graveyard         = @()
                commandZone       = @("Ur-Dragon")
            },
            @{
                seat              = 2
                name              = "TestPlayer2"
                life              = 35
                manaAvailable     = 4
                landCount         = 4
                creaturesOnField  = 2
                totalPowerOnBoard = 5
                hand              = @()
                handCount         = 3
                battlefield       = @("Mountain", "Mountain", "Mountain", "Mountain", "Goblin Guide", "Monastery Swiftspear")
                graveyard         = @()
                commandZone       = @("Krenko, Mob Boss")
            },
            @{
                seat              = 3
                name              = "TestPlayer3"
                life              = 40
                manaAvailable     = 0
                landCount         = 0
                creaturesOnField  = 0
                totalPowerOnBoard = 0
                hand              = @()
                handCount         = 7
                battlefield       = @()
                graveyard         = @()
                commandZone       = @("Prossh, Skyraider of Kher")
            }
        )
    } | ConvertTo-Json -Depth 10

    $resp = Invoke-RestMethod `
        -Uri     "$BaseUrl/api/policy/decide" `
        -Method  Post `
        -Body    $body `
        -ContentType "application/json" `
        -TimeoutSec 30

    if ($Verbose) {
        Write-Host ""
        Write-Host "  Full /decide response:" -ForegroundColor White
        $resp | ConvertTo-Json -Depth 6 | Write-Host
    }

    # Validate shape of response
    $ok = $true
    if ([string]::IsNullOrEmpty($resp.action)) {
        Write-Fail "  response.action is empty"
        $ok = $false
    }
    if ($null -eq $resp.confidence) {
        Write-Fail "  response.confidence is missing"
        $ok = $false
    }
    if ($resp.PSObject.Properties["error"] -and -not [string]::IsNullOrEmpty($resp.error)) {
        Write-Fail "  Server returned an error: $($resp.error)"
        $ok = $false
    }

    if ($ok) {
        $confPct = [math]::Round($resp.confidence * 100, 1)
        Write-Pass "Decision received  →  action='$($resp.action)'  confidence=$($confPct)%  latency=$($resp.inference_ms)ms  src=$($resp.vector_source)"

        # Top-3 probabilities
        if ($resp.probabilities) {
            $top3 = $resp.probabilities.PSObject.Properties |
                Sort-Object { $_.Value } -Descending |
                Select-Object -First 3
            Write-Info "Top-3 probabilities:"
            foreach ($p in $top3) {
                $pct = [math]::Round($p.Value * 100, 1)
                Write-Info "  $($p.Name.PadRight(20)) $pct%"
            }
        }
    } else {
        $script:allPassed = $false
    }
}

# ─── Step 4: Verify the decide log line appeared ──────────────────────────────

Invoke-Step "Step 4 — Confirm [routes.policy.decide] log line guidance" {
    Write-Info "The /decide endpoint logs at INFO level — you should see a line like:"
    Write-Info "  [decide] turn=3 phase=main_1 → cast_ramp (conf=0.810) | top5=[...] | src=encoder"
    Write-Info ""
    Write-Info "If that line is MISSING from your server console:"
    Write-Info "  1. Confirm uvicorn is started with --log-level info (default)"
    Write-Info "  2. Check that lab_api.py calls register_policy_routes(app, policy_service)"
    Write-Info "  3. Confirm routes/policy.py is included in the app router (see routes/__init__.py)"
    Write-Info "  4. The log name is 'routes.policy.decide' — ensure logging isn't filtered"
    Write-Pass "Guidance printed"
}

# ─── Step 5: Why Forge still ignores the policy server ───────────────────────

Invoke-Step "Step 5 — Forge IPC connection status (informational)" {
    Write-Warn "Forge does NOT call /api/policy/decide automatically."
    Write-Warn "routes/game.py POST /api/game/start has a TODO: 'Wire Forge engine launch here'."
    Write-Warn ""
    Write-Warn "Until the IPC bridge is wired, you will only see /decide hits from:"
    Write-Warn "  - This smoke-test script"
    Write-Warn "  - overnight-run.py  (batch simulation path)"
    Write-Warn "  - A manual curl/Invoke-RestMethod call"
    Write-Warn ""
    Write-Warn "Forge (Commander) launches its own built-in AI and plays lands/passes"
    Write-Warn "because it has no HTTP client pointed at localhost:8000."
    Write-Warn ""
    Write-Warn "Next step: wire GameSession launch inside POST /api/game/start,"
    Write-Warn "or add a PolicyClient HTTP hook in Forge's AiController."
    Write-Pass "Status explained"
}

# ─── Summary ─────────────────────────────────────────────────────────────────

Write-Host ""
if ($allPassed) {
    Write-Host "══════════════════════════════════════════" -ForegroundColor Green
    Write-Host "  ALL STEPS PASSED — policy server is live" -ForegroundColor Green
    Write-Host "══════════════════════════════════════════" -ForegroundColor Green
} else {
    Write-Host "══════════════════════════════════════════" -ForegroundColor Red
    Write-Host "  ONE OR MORE STEPS FAILED — see output above" -ForegroundColor Red
    Write-Host "══════════════════════════════════════════" -ForegroundColor Red
    exit 1
}
