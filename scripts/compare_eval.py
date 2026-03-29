#!/usr/bin/env python
"""
Commander AI Lab — Compare Eval Results (Issue #153)
═════════════════════════════════════════════════════
Loads two eval result JSONs produced by eval_policy.py, computes
win-rate delta, 95% CI, and Fisher's exact test for significance.

Usage:
    python scripts/compare_eval.py \
        --baseline results/eval-baseline.json \
        --forge    results/eval-forge.json

    # Custom threshold
    python scripts/compare_eval.py \
        --baseline results/eval-baseline.json \
        --forge    results/eval-forge.json \
        --min-delta 0.05 \
        --alpha 0.05

Exit codes:
    0  — Forge model passes (delta >= min-delta AND p < alpha)
    1  — Forge model fails (delta below threshold OR not significant)
    2  — Input error (missing files, bad JSON)
"""

import argparse
import json
import math
import sys
from pathlib import Path


# ─────────────────────────────────────────────
# Statistics helpers
# ─────────────────────────────────────────────

def wilson_ci(wins: int, n: int, z: float = 1.96):
    """Wilson score interval for a proportion."""
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    denom = 1 + z ** 2 / n
    centre = (p + z ** 2 / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def fishers_exact(a_wins, a_n, b_wins, b_n):
    """
    Two-tailed Fisher's exact test.
    Contingency table:
        [[a_wins, a_n - a_wins],
         [b_wins, b_n - b_wins]]

    Returns (odds_ratio, p_value).
    Uses scipy if available, otherwise a pure-Python hypergeometric
    approximation suitable for n >= 50.
    """
    try:
        from scipy.stats import fisher_exact
        table = [
            [a_wins, a_n - a_wins],
            [b_wins, b_n - b_wins],
        ]
        oddsratio, pvalue = fisher_exact(table, alternative="two-sided")
        return float(oddsratio), float(pvalue)
    except ImportError:
        pass

    # Pure-Python fallback: hypergeometric tail sum (two-tailed)
    # Works well when all cell counts >= 5
    def _log_comb(n, k):
        if k < 0 or k > n:
            return -math.inf
        return (
            sum(math.log(n - i) for i in range(k))
            - sum(math.log(i + 1) for i in range(k))
        )

    N = a_n + b_n
    K = a_wins + b_wins  # total wins
    n = a_n              # first group size
    k_obs = a_wins

    log_denom = _log_comb(N, K)
    p_obs = math.exp(_log_comb(n, k_obs) + _log_comb(N - n, K - k_obs) - log_denom)

    p_val = 0.0
    k_lo = max(0, K - b_n)
    k_hi = min(K, n)
    for k in range(k_lo, k_hi + 1):
        p_k = math.exp(_log_comb(n, k) + _log_comb(N - n, K - k) - log_denom)
        if p_k <= p_obs + 1e-10:
            p_val += p_k

    a_loss = a_n - a_wins
    b_loss = b_n - b_wins
    or_val = (
        (a_wins * b_loss / (a_loss * b_wins))
        if a_loss > 0 and b_wins > 0
        else float("inf")
    )
    return or_val, min(p_val, 1.0)


# ─────────────────────────────────────────────
# JSON loader
# ─────────────────────────────────────────────

def load_result(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(p) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(2)

    # Accept both {summary: {...}} and flat {win_rate: ...} shapes
    if "summary" in data:
        return data["summary"]
    return data


# ─────────────────────────────────────────────
# Comparison table printer
# ─────────────────────────────────────────────

def fmt_pct(v) -> str:
    try:
        return f"{float(v):.1%}"
    except (TypeError, ValueError):
        return str(v)


def fmt_f(v, dp=2) -> str:
    try:
        return f"{float(v):.{dp}f}"
    except (TypeError, ValueError):
        return str(v)


def print_comparison(b: dict, f: dict, delta: float, ci_lo: float, ci_hi: float,
                     odds: float, pval: float, min_delta: float, alpha: float):
    W = 62
    SEP = "─" * W

    def row(label, bval, fval, delta_str=""):
        print(f"  {label:<28}  {bval:>10}  {fval:>10}  {delta_str:>8}")

    print()
    print("=" * W)
    print("  COMMANDER AI LAB — EVAL COMPARISON")
    print("=" * W)
    print(f"  Baseline : {b.get('checkpoint_path', b.get('run_id', '?'))}")
    print(f"  Forge    : {f.get('checkpoint_path', f.get('run_id', '?'))}")
    print(SEP)
    print(f"  {'Metric':<28}  {'Baseline':>10}  {'Forge':>10}  {'Delta':>8}")
    print(SEP)

    b_n, f_n = int(b.get("num_games", 0)), int(f.get("num_games", 0))
    b_w, f_w = int(b.get("wins", 0)), int(f.get("wins", 0))

    row("Games",     str(b_n),         str(f_n))
    row("Wins",      str(b_w),         str(f_w),        f"{f_w - b_w:+d}")
    row("Win rate",  fmt_pct(b.get("win_rate")), fmt_pct(f.get("win_rate")),
        f"{delta:+.1%}")

    b_lo, b_hi = wilson_ci(b_w, b_n)
    f_lo, f_hi = wilson_ci(f_w, f_n)
    row("  95% CI",
        f"[{fmt_pct(b_lo)}, {fmt_pct(b_hi)}]",
        f"[{fmt_pct(f_lo)}, {fmt_pct(f_hi)}]",
    )
    row("  Δ 95% CI", "", "", f"[{ci_lo:+.1%}, {ci_hi:+.1%}]")
    print(SEP)
    row("Avg turns",
        fmt_f(b.get("avg_turns")),
        fmt_f(f.get("avg_turns")),
        fmt_f(float(f.get("avg_turns", 0)) - float(b.get("avg_turns", 0)), 1))
    row("Avg life Δ",
        fmt_f(b.get("avg_life_delta")),
        fmt_f(f.get("avg_life_delta")),
        fmt_f(float(f.get("avg_life_delta", 0)) - float(b.get("avg_life_delta", 0)), 1))
    row("Avg cmd dmg",
        fmt_f(b.get("avg_commander_damage")),
        fmt_f(f.get("avg_commander_damage")),
        fmt_f(float(f.get("avg_commander_damage", 0)) - float(b.get("avg_commander_damage", 0)), 1))
    row("Illegal acts/g",
        fmt_f(b.get("avg_illegal_actions")),
        fmt_f(f.get("avg_illegal_actions")),
        fmt_f(float(f.get("avg_illegal_actions", 0)) - float(b.get("avg_illegal_actions", 0)), 2))
    row("Avg entropy",
        fmt_f(b.get("avg_entropy"), 4),
        fmt_f(f.get("avg_entropy"), 4),
        fmt_f(float(f.get("avg_entropy", 0)) - float(b.get("avg_entropy", 0)), 4))
    row("Avg infer ms",
        fmt_f(b.get("avg_inference_ms"), 1),
        fmt_f(f.get("avg_inference_ms"), 1),
        fmt_f(float(f.get("avg_inference_ms", 0)) - float(b.get("avg_inference_ms", 0)), 1))
    print(SEP)

    # Significance block
    print(f"  Fisher's exact test (two-tailed)")
    print(f"    odds ratio : {odds:.4f}")
    print(f"    p-value    : {pval:.6f}")
    print(f"    alpha      : {alpha}")
    print(SEP)

    # Pass / fail verdict
    delta_pass = delta >= min_delta
    sig_pass   = pval < alpha
    passed     = delta_pass and sig_pass

    if passed:
        verdict = "PASS  ✓  Forge model outperforms baseline"
    elif not delta_pass and not sig_pass:
        verdict = f"FAIL  ✗  delta ({delta:+.1%}) < {min_delta:.1%} AND not significant (p={pval:.4f})"
    elif not delta_pass:
        verdict = f"FAIL  ✗  delta ({delta:+.1%}) < threshold ({min_delta:.1%})"
    else:
        verdict = f"FAIL  ✗  not statistically significant (p={pval:.4f} >= alpha={alpha})"

    print(f"  {verdict}")
    print("=" * W)
    print()


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Compare two eval result JSONs from eval_policy.py.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--baseline", required=True, help="Baseline (synthetic) eval JSON")
    p.add_argument("--forge",    required=True, help="Forge-trained eval JSON")
    p.add_argument("--min-delta", type=float, default=0.05,
                   help="Minimum absolute win-rate improvement to pass")
    p.add_argument("--alpha", type=float, default=0.05,
                   help="Significance level for Fisher's exact test")
    p.add_argument("--json-out", default="",
                   help="Optional: write comparison result to this JSON file")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    b = load_result(args.baseline)
    f = load_result(args.forge)

    b_n, f_n = int(b.get("num_games", 0)), int(f.get("num_games", 0))
    b_w, f_w = int(b.get("wins", 0)), int(f.get("wins", 0))
    b_wr = b_w / max(b_n, 1)
    f_wr = f_w / max(f_n, 1)

    delta = f_wr - b_wr

    # Delta 95% CI via normal approximation
    se_b = math.sqrt(b_wr * (1 - b_wr) / max(b_n, 1))
    se_f = math.sqrt(f_wr * (1 - f_wr) / max(f_n, 1))
    se_delta = math.sqrt(se_b ** 2 + se_f ** 2)
    ci_lo = delta - 1.96 * se_delta
    ci_hi = delta + 1.96 * se_delta

    odds, pval = fishers_exact(b_w, b_n, f_w, f_n)

    print_comparison(b, f, delta, ci_lo, ci_hi, odds, pval, args.min_delta, args.alpha)

    if args.json_out:
        out = {
            "baseline": args.baseline,
            "forge": args.forge,
            "baseline_win_rate": b_wr,
            "forge_win_rate": f_wr,
            "delta": delta,
            "delta_ci95_low": ci_lo,
            "delta_ci95_high": ci_hi,
            "odds_ratio": odds,
            "p_value": pval,
            "alpha": args.alpha,
            "min_delta": args.min_delta,
            "passed": delta >= args.min_delta and pval < args.alpha,
        }
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w") as jf:
            json.dump(out, jf, indent=2)
        print(f"Comparison JSON written to: {args.json_out}")

    passed = delta >= args.min_delta and pval < args.alpha
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
