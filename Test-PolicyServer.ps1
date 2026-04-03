<#
.SYNOPSIS
    Smoke-tests the Commander AI Lab policy server from PowerShell.
    Checks: server reachable -> /api/policy/health -> /api/policy/decide.
    Prints a plain-English pass/fail for every step.

.USAGE
    # From repo root (server already running in another window):
    .\Test-PolicyServer.ps1

    # Custom host/port:
    .\Test-PolicyServer.ps1 -BaseUrl http://localhost:9000

    # Pretty-print the full decide response:
    .\Test-PolicyServer.ps1 -Verbose
#>
param(
    [string]$BaseUrl = "http://localhost:8080",
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

# ---- helpers ----------------------------------------------------------------

function Write-Pass { param([string]$msg) Write-Host "  [PASS] $msg" -ForegroundColor Green  }
function Write-Fail { param([string]$msg) Write-Host "  [FAIL] $msg" -ForegroundColor Red    }
function Write-Info { param([string]$msg) Write-Host "  [INFO] $msg" -ForegroundColor Cyan   }
function Write-Warn { param([string]$msg) Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Step { param([string]$msg) Write-Host "`n-- $msg" -ForegroundColor White       }

$allPassed = $true

function Invoke-Step {
    param(
        [string]      $Name,
        [scriptblock] $Block
    )
    Write-Step $Name
    try   { & $Block }
    catch {
        Write-Fail $_.Exception.Message
        $script:allPassed = $false
    }
}

# ---- Step 1: server reachable -----------------------------------------------

Invoke-Step "Step 1 -- Server reachable at $BaseUrl" {
    $r1 = $null
    try { $r1 = Invoke-WebRequest -Uri "$BaseUrl/docs" -UseBasicParsing -TimeoutSec 5 } catch {}
    if ($r1 -and $r1.StatusCode -eq 200) {
        Write-Pass "FastAPI server is up (GET /docs -> 200)"
        return
    }
    $r2 = $null
    try { $r2 = Invoke-WebRequest -Uri "$BaseUrl/" -UseBasicParsing -TimeoutSec 5 } catch {}
    if ($r2 -and $r2.StatusCode -lt 500) {
        Write-Pass "FastAPI server is up (GET / -> $($r2.StatusCode))"
        return
    }
    throw "Cannot reach $BaseUrl -- is lab_api.py / uvicorn running?"
}

# ---- Step 2: /api/policy/health ---------------------------------------------

$modelLoaded = $false

Invoke-Step "Step 2 -- GET $BaseUrl/api/policy/health" {
    $resp = Invoke-RestMethod -Uri "$BaseUrl/api/policy/health" -Method Get -TimeoutSec 10
    if ($Verbose) { $resp | ConvertTo-Json -Depth 5 | Write-Host }

    if ($resp.ready -eq $true) {
        Write-Pass "Model is loaded and ready  (ready=true)"
        $script:modelLoaded = $true
    } elseif ($resp.status -eq "degraded") {
        Write-Fail "Health returned status=degraded / ready=false"
        Write-Warn "  -> Policy model is NOT loaded."
        Write-Warn "  -> Start the server with --load-policy, or call POST /api/ml/load_model first."
        Write-Warn "  -> Confirm models/ contains a valid .pt checkpoint."
        $script:allPassed = $false
    } else {
        Write-Warn "Unexpected health response -- dumping:"
        $resp | ConvertTo-Json -Depth 5 | Write-Host
        $script:allPassed = $false
    }
}

# ---- Step 3: /api/policy/decide (synthetic snapshot) ------------------------

Invoke-Step "Step 3 -- POST $BaseUrl/api/policy/decide  (synthetic 4-player snapshot)" {

    if (-not $script:modelLoaded) {
        Write-Warn "Skipping /decide -- model not loaded (Step 2 failed)."
        Write-Warn "Fix Step 2 first, then re-run."
        return
    }

    $body = [ordered]@{
        game_id       = "ps1-smoke-test"
        turn          = 3
        phase         = "MAIN1"
        active_player = 0
        playstyle     = "midrange"
        temperature   = 1.0
        greedy        = $false
        players       = @(
            [ordered]@{
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
                commandZone       = @("Atraxa, Praetors Voice")
            },
            [ordered]@{
                seat              = 1
                name              = "TestPlayer1"
                life              = 38
                manaAvailable     = 2
                landCount         = 2
                creaturesOnField  = 0
                totalPowerOnBoard = 0
                handCount         = 4
                hand              = @()
                battlefield       = @("Island", "Swamp")
                graveyard         = @()
                commandZone       = @("Ur-Dragon")
            },
            [ordered]@{
                seat              = 2
                name              = "TestPlayer2"
                life              = 35
                manaAvailable     = 4
                landCount         = 4
                creaturesOnField  = 2
                totalPowerOnBoard = 5
                handCount         = 3
                hand              = @()
                battlefield       = @("Mountain", "Mountain", "Mountain", "Mountain", "Goblin Guide", "Monastery Swiftspear")
                graveyard         = @()
                commandZone       = @("Krenko, Mob Boss")
            },
            [ordered]@{
                seat              = 3
                name              = "TestPlayer3"
                life              = 40
                manaAvailable     = 0
                landCount         = 0
                creaturesOnField  = 0
                totalPowerOnBoard = 0
                handCount         = 7
                hand              = @()
                battlefield       = @()
                graveyard         = @()
                commandZone       = @("Prossh, Skyraider of Kher")
            }
        )
    } | ConvertTo-Json -Depth 10

    $resp = Invoke-RestMethod `
        -Uri         "$BaseUrl/api/policy/decide" `
        -Method      Post `
        -Body        $body `
        -ContentType "application/json" `
        -TimeoutSec  30

    if ($Verbose) {
        Write-Host ""
        Write-Host "  Full /decide response:" -ForegroundColor White
        $resp | ConvertTo-Json -Depth 6 | Write-Host
    }

    $ok = $true
    if ([string]::IsNullOrEmpty($resp.action)) {
        Write-Fail "response.action is empty"
        $ok = $false
    }
    if ($null -eq $resp.confidence) {
        Write-Fail "response.confidence is missing"
        $ok = $false
    }
    if ($resp.PSObject.Properties["error"] -and -not [string]::IsNullOrEmpty($resp.error)) {
        Write-Fail "Server returned error: $($resp.error)"
        $ok = $false
    }

    if ($ok) {
        $confPct = [math]::Round($resp.confidence * 100, 1)
        Write-Pass "Decision received  ->  action='$($resp.action)'  conf=$($confPct)%  latency=$($resp.inference_ms)ms  src=$($resp.vector_source)"

        if ($resp.probabilities) {
            $top3 = $resp.probabilities.PSObject.Properties |
                Sort-Object { $_.Value } -Descending |
                Select-Object -First 3
            Write-Info "Top-3 action probabilities:"
            foreach ($p in $top3) {
                $pct = [math]::Round($p.Value * 100, 1)
                Write-Info ("  " + $p.Name.PadRight(22) + "$pct%")
            }
        }
    } else {
        $script:allPassed = $false
    }
}

# ---- Step 4: log line guidance ----------------------------------------------

Invoke-Step "Step 4 -- Confirm [routes.policy.decide] log line in server console" {
    Write-Info "After Step 3 you should see in the uvicorn window:"
    Write-Info "  [decide] turn=3 phase=main_1 -> cast_ramp (conf=0.810) | top5=[...] | src=encoder"
    Write-Info ""
    Write-Info "If that line is MISSING:"
    Write-Info "  1. Confirm uvicorn started with --log-level info (the default)"
    Write-Info "  2. Confirm lab_api.py calls register_policy_routes(app, policy_svc)"
    Write-Info "  3. Confirm routes/policy.py is included via routes/__init__.py"
    Write-Info "  4. Logger name is [routes.policy.decide] -- check no filter silences it"
    Write-Pass "Guidance printed"
}

# ---- Step 5: why Forge ignores the policy server ----------------------------

Invoke-Step "Step 5 -- Forge IPC status (informational)" {
    Write-Warn "Forge does NOT call /api/policy/decide on its own."
    Write-Warn "routes/game.py POST /api/game/start has a TODO: wire Forge engine launch."
    Write-Warn ""
    Write-Warn "Until wired, /decide is only hit by:"
    Write-Warn "  - This script"
    Write-Warn "  - overnight-run.py  (batch sim path)"
    Write-Warn "  - Manual Invoke-RestMethod / curl calls"
    Write-Warn ""
    Write-Warn "Forge launches its built-in AI and plays lands because it has"
    Write-Warn "no HTTP client pointed at localhost:8080."
    Write-Warn ""
    Write-Warn "Next step: wire GameSession inside POST /api/game/start,"
    Write-Warn "or add a PolicyClient hook in Forge AiController.java."
    Write-Pass "Status explained"
}

# ---- Summary ----------------------------------------------------------------

Write-Host ""
if ($allPassed) {
    Write-Host "==========================================" -ForegroundColor Green
    Write-Host "  ALL STEPS PASSED -- policy server live"  -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
} else {
    Write-Host "==========================================" -ForegroundColor Red
    Write-Host "  ONE OR MORE STEPS FAILED -- see above"   -ForegroundColor Red
    Write-Host "==========================================" -ForegroundColor Red
    exit 1
}
