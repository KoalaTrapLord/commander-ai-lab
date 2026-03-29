#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Commander AI Lab - full benchmark pipeline (Issue #153)

.DESCRIPTION
    Chains all four steps of the Forge-vs-Synthetic eval benchmark:
      1. Train baseline model (synthetic self-play)
      2. Train Forge model (--data-source forge)
      3. Eval both checkpoints vs Forge built-in (200 games each)
      4. Compare results with Fisher's exact test

    Writes all artefacts to:
      ml/models/checkpoints/baseline-synthetic/
      ml/models/checkpoints/forge-trained/
      results/eval-baseline.json
      results/eval-forge.json
      results/compare-result.json   <- pass/fail verdict

.PARAMETER Iterations
    PPO training iterations for each model. Default: 100

.PARAMETER EpisodesPerIter
    Self-play / Forge episodes per iteration. Default: 64

.PARAMETER EvalGames
    Evaluation games per model. Default: 200

.PARAMETER Threads
    Parallel Forge workers for eval. Default: 4

.PARAMETER Seed
    Optional RNG seed (passed to both eval runs for reproducibility).

.PARAMETER ForgeResultsDir
    Directory where Forge writes ml-decisions-forge-*.jsonl files.
    Default: results

.PARAMETER ForgeBatchId
    Batch ID prefix used when the Forge producer writes JSONL files.
    Default: forge-batch

.PARAMETER ForgeNumGames
    Total Forge games the producer will consume during Forge training.
    Default: 256

.PARAMETER MinDelta
    Minimum absolute win-rate improvement to pass the benchmark. Default: 0.05

.PARAMETER Alpha
    Significance level for Fisher's exact test. Default: 0.05

.PARAMETER SkipTraining
    Skip both training steps (use existing checkpoints).

.PARAMETER SkipEval
    Skip both eval steps (use existing result JSONs).

.EXAMPLE
    .\run_benchmark.ps1

.EXAMPLE
    .\run_benchmark.ps1 -Iterations 10 -EpisodesPerIter 16 -EvalGames 50

.EXAMPLE
    .\run_benchmark.ps1 -SkipTraining -SkipEval
#>

[CmdletBinding()]
param(
    [int]    $Iterations      = 100,
    [int]    $EpisodesPerIter = 64,
    [int]    $EvalGames       = 200,
    [int]    $Threads         = 4,
    [int]    $Seed            = -1,
    [string] $ForgeResultsDir = "results",
    [string] $ForgeBatchId    = "forge-batch",
    [int]    $ForgeNumGames   = 256,
    [double] $MinDelta        = 0.05,
    [double] $Alpha           = 0.05,
    [switch] $SkipTraining,
    [switch] $SkipEval
)

$ErrorActionPreference = "Stop"

# Paths
$BaselineDir  = "ml/models/checkpoints/baseline-synthetic"
$ForgeDir     = "ml/models/checkpoints/forge-trained"
$BaselineJson = "results/eval-baseline.json"
$ForgeJson    = "results/eval-forge.json"
$CompareJson  = "results/compare-result.json"

# Helpers
function Banner([string]$msg) {
    $line = "=" * 62
    Write-Host ""
    Write-Host $line -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host $line -ForegroundColor Cyan
    Write-Host ""
}

function Step([string]$msg) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')]  $msg" -ForegroundColor Yellow
}

function Ok([string]$msg) {
    Write-Host "  OK  $msg" -ForegroundColor Green
}

function Err([string]$msg) {
    Write-Host "  FAIL  $msg" -ForegroundColor Red
}

function Run([string[]]$cmd) {
    $display = $cmd -join " "
    Step "Running: $display"
    & $cmd[0] $cmd[1..($cmd.Length-1)]
    if ($LASTEXITCODE -ne 0) {
        Err "Command failed (exit $LASTEXITCODE): $display"
        exit $LASTEXITCODE
    }
}

# Setup
$null = New-Item -ItemType Directory -Force -Path "logs/benchmark", "results" | Out-Null

$SeedArgs = @()
if ($Seed -ge 0) { $SeedArgs = @("--seed", "$Seed") }

$StartTime = Get-Date
Banner "Commander AI Lab - Benchmark Pipeline (Issue #153)"

Write-Host "  Iterations      : $Iterations"
Write-Host "  Episodes/iter   : $EpisodesPerIter"
Write-Host "  Eval games      : $EvalGames"
Write-Host "  Eval threads    : $Threads"
Write-Host "  Seed            : $(if ($Seed -ge 0) { $Seed } else { '(random)' })"
Write-Host "  Min delta       : $($MinDelta * 100)%"
Write-Host "  Alpha           : $Alpha"
Write-Host "  Skip training   : $SkipTraining"
Write-Host "  Skip eval       : $SkipEval"
Write-Host ""

# STEP 1 - Train baseline
if (-not $SkipTraining) {
    Banner "Step 1/4 - Training baseline (synthetic)"
    $t0 = Get-Date

    Run @(
        "python", "-m", "ml.training.ppo_trainer",
        "--data-source",       "synthetic",
        "--iterations",        "$Iterations",
        "--episodes-per-iter", "$EpisodesPerIter",
        "--checkpoint-dir",    $BaselineDir,
        "--save-every",        "10",
        "--eval-every",        "5"
    )

    $elapsed = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    Ok "Baseline training complete in $elapsed min"
    Ok "Checkpoints in: $BaselineDir"
} else {
    Step "Skipping training (-SkipTraining flag set)"
}

# STEP 2 - Train Forge model
if (-not $SkipTraining) {
    Banner "Step 2/4 - Training Forge model"
    $t0 = Get-Date

    Run @(
        "python", "-m", "ml.training.ppo_trainer",
        "--data-source",       "forge",
        "--iterations",        "$Iterations",
        "--episodes-per-iter", "$EpisodesPerIter",
        "--checkpoint-dir",    $ForgeDir,
        "--forge-results-dir", $ForgeResultsDir,
        "--forge-batch-id",    $ForgeBatchId,
        "--forge-num-games",   "$ForgeNumGames",
        "--save-every",        "10",
        "--eval-every",        "5"
    )

    $elapsed = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    Ok "Forge training complete in $elapsed min"
    Ok "Checkpoints in: $ForgeDir"
} else {
    Step "Skipping training (-SkipTraining flag set)"
}

# STEP 3 - Eval
if (-not $SkipEval) {
    Banner "Step 3a/4 - Evaluating baseline checkpoint"

    $BaselinePt = "$BaselineDir/best_ppo.pt"
    if (-not (Test-Path $BaselinePt)) {
        $BaselinePt = Get-ChildItem "$BaselineDir/ppo_iter_*.pt" |
                      Sort-Object Name -Descending |
                      Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $BaselinePt -or -not (Test-Path $BaselinePt)) {
        Err "No checkpoint found in $BaselineDir - run training first"
        exit 1
    }
    Step "Using checkpoint: $BaselinePt"
    $t0 = Get-Date

    Run (@(
        "python", "scripts/eval_policy.py",
        "--model",   $BaselinePt,
        "--games",   "$EvalGames",
        "--run-id",  "baseline-synthetic",
        "--out",     $BaselineJson,
        "--threads", "$Threads"
    ) + $SeedArgs)

    $elapsed = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    Ok "Baseline eval complete in $elapsed min -> $BaselineJson"

    Banner "Step 3b/4 - Evaluating Forge checkpoint"

    $ForgePt = "$ForgeDir/best_ppo.pt"
    if (-not (Test-Path $ForgePt)) {
        $ForgePt = Get-ChildItem "$ForgeDir/ppo_iter_*.pt" |
                   Sort-Object Name -Descending |
                   Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $ForgePt -or -not (Test-Path $ForgePt)) {
        Err "No checkpoint found in $ForgeDir - run training first"
        exit 1
    }
    Step "Using checkpoint: $ForgePt"
    $t0 = Get-Date

    Run (@(
        "python", "scripts/eval_policy.py",
        "--model",   $ForgePt,
        "--games",   "$EvalGames",
        "--run-id",  "forge-trained",
        "--out",     $ForgeJson,
        "--threads", "$Threads"
    ) + $SeedArgs)

    $elapsed = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    Ok "Forge eval complete in $elapsed min -> $ForgeJson"
} else {
    Step "Skipping eval (-SkipEval flag set)"
}

# STEP 4 - Compare
Banner "Step 4/4 - Comparing results"

if (-not (Test-Path $BaselineJson)) {
    Err "Baseline result not found: $BaselineJson"
    exit 1
}
if (-not (Test-Path $ForgeJson)) {
    Err "Forge result not found: $ForgeJson"
    exit 1
}

python scripts/compare_eval.py `
    --baseline  $BaselineJson `
    --forge     $ForgeJson `
    --min-delta $MinDelta `
    --alpha     $Alpha `
    --json-out  $CompareJson

$exitCode = $LASTEXITCODE

$totalMin = [math]::Round(((Get-Date) - $StartTime).TotalMinutes, 1)
Banner "Benchmark Complete"
Write-Host "  Total wall time : $totalMin min"
Write-Host "  Baseline JSON   : $BaselineJson"
Write-Host "  Forge JSON      : $ForgeJson"
Write-Host "  Compare JSON    : $CompareJson"
Write-Host ""

if ($exitCode -eq 0) {
    Ok "PASSED - Forge model meets the benchmark threshold."
    Write-Host ""
    Write-Host "  Next steps:" -ForegroundColor Cyan
    Write-Host "    git add results/eval-baseline.json results/eval-forge.json results/compare-result.json"
    Write-Host "    git commit -m 'results: forge-vs-synthetic benchmark run'"
    Write-Host "    git push"
} else {
    Err "FAILED - Forge model did not meet the benchmark threshold."
    Write-Host "  Check $CompareJson for details." -ForegroundColor Yellow
}

Write-Host ""
exit $exitCode
