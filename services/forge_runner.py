"""Forge batch simulation runner: Java discovery, command building, process management."""
import asyncio
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime as _datetime
from pathlib import Path
from typing import Optional

from models.state import CFG, BatchState
from services.deck_service import parse_dck_file, _load_deck_cards_by_name

log = logging.getLogger("lab.batch")
log_sim = logging.getLogger("commander_ai_lab.sim")

# Global DeepSeek brain instance (lazy-initialized)
_deepseek_brain = None
_deepseek_lock = threading.Lock()


def _find_java17() -> str:
    search_dirs = [r'C:\Program Files\Eclipse Adoptium', r'C:\Program Files\Java']
    for d in search_dirs:
        if os.path.isdir(d):
            for child in os.listdir(d):
                if child.startswith('jdk-17'):
                    candidate = os.path.join(d, child, 'bin', 'java.exe')
                    if os.path.isfile(candidate):
                        return candidate
    return 'java'


_JAVA17_PATH = None


def get_java17() -> str:
    global _JAVA17_PATH
    if _JAVA17_PATH is None:
        _JAVA17_PATH = _find_java17()
    return _JAVA17_PATH


def build_java_command(
    decks: list, num_games: int, threads: int, seed: Optional[int],
    clock: int, output_path: str, use_learned_policy: bool = False,
    policy_server: str = "http://localhost:8080", policy_style: str = "midrange",
    policy_greedy: bool = False, ai_simplified: bool = False,
    ai_think_time_ms: int = -1, max_queue_depth: int = -1,
) -> list:
    java17 = get_java17()
    forge_jar = CFG.forge_jar
    cmd = [
        java17, '-jar', forge_jar, '-sim',
        '-decks', ','.join(str(d) for d in decks),
        '-games', str(num_games),
        '-threads', str(threads),
        '-clock', str(clock),
        '-output', output_path,
    ]
    if seed is not None:
        cmd += ['-seed', str(seed)]
    if use_learned_policy:
        cmd += ['-policy', policy_style, '-policyServer', policy_server]
    if policy_greedy:
        cmd += ['-policyGreedy']
    if ai_simplified:
        cmd += ['-aiSimplified']
    if ai_think_time_ms > 0:
        cmd += ['-aiThinkTimeMs', str(ai_think_time_ms)]
    if max_queue_depth > 0:
        cmd += ['-maxQueueDepth', str(max_queue_depth)]
    return cmd


def _run_process_blocking(state: BatchState, cmd: list):
    """Run Forge subprocess, parse progress, generate deck reports."""
    log.info(f"Running: {' '.join(cmd)}")
    state.started_at = datetime.datetime.now().isoformat()
    state.status = "running"
    env = os.environ.copy()
    java17 = get_java17()
    java_bin = os.path.dirname(java17)
    if java_bin:
        env["JAVA_HOME"] = os.path.dirname(java_bin)
        env["PATH"] = java_bin + os.pathsep + env.get("PATH", "")
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
    except Exception as e:
        state.status = "error"
        state.error = str(e)
        log.error(f"Failed to start subprocess: {e}")
        return
    last_activity = [time.monotonic()]
    stall_limit = 300  # 5 min
    def watchdog():
        while proc.poll() is None:
            if (time.monotonic() - last_activity[0]) > stall_limit:
                log.warning("Stall detected, killing process")
                proc.kill()
                state.status = "error"
                state.error = "Stall detected (5 min no output)"
                return
            time.sleep(5)
    wd = threading.Thread(target=watchdog, daemon=True)
    wd.start()
    output_lines = []
    for line in proc.stdout:
        last_activity[0] = time.monotonic()
        line = line.rstrip()
        output_lines.append(line)
        gm = re.match(r'\[Game (\d+)/(\d+)\]', line)
        if gm:
            state.games_done = int(gm.group(1))
            state.games_total = int(gm.group(2))
        pm = re.match(r'\[PROGRESS\].*?(\d+\.?\d*)\s*sims/sec', line)
        if pm:
            state.throughput = float(pm.group(1))
    proc.wait()
    state.log = '\n'.join(output_lines)
    if proc.returncode != 0:
        state.status = "error"
        state.error = f"Exit code {proc.returncode}"
    else:
        state.status = "done"
        state.games_done = state.games_total
    state.ended_at = datetime.datetime.now().isoformat()


async def run_batch_subprocess(
    state: BatchState, decks: list, num_games: int, threads: int,
    seed: Optional[int] = None, clock: int = 6000, output_path: str = "results",
    use_learned_policy: bool = False, **kwargs,
):
    """Async wrapper that runs Forge subprocess in executor."""
    cmd = build_java_command(
        decks, num_games, threads, seed, clock, output_path,
        use_learned_policy=use_learned_policy, **kwargs,
    )
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_process_blocking, state, cmd)


def _get_deepseek_brain():
    """Get or create the global DeepSeek brain instance."""
    global _deepseek_brain
    if _deepseek_brain is None:
        with _deepseek_lock:
            if _deepseek_brain is None:
                try:
                    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
                    src_dir = os.path.normpath(src_dir)
                    if src_dir not in sys.path:
                        sys.path.insert(0, src_dir)
                    from commander_ai_lab.sim.deepseek_brain import DeepSeekBrain, DeepSeekConfig
                    cfg = DeepSeekConfig()
                    # Allow env var overrides
                    if os.environ.get('DEEPSEEK_API_BASE'):
                        cfg.api_base = os.environ['DEEPSEEK_API_BASE']
                    if os.environ.get('DEEPSEEK_MODEL'):
                        cfg.model = os.environ['DEEPSEEK_MODEL']
                    cfg.log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs', 'decisions')
                    cfg.log_dir = os.path.normpath(cfg.log_dir)
                    _deepseek_brain = DeepSeekBrain(cfg)
                except Exception as e:
                    log_sim.error(f'Failed to initialize brain: {e}')
                    return None
    return _deepseek_brain


def _run_deepseek_batch_thread(
    state: BatchState,
    deck_names: list,
    num_games: int,
    output_path: str,
):
    """Run batch simulation using Python sim engine + DeepSeek AI opponent."""
    try:
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
        src_dir = os.path.normpath(src_dir)
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        from commander_ai_lab.sim.models import Card
        from commander_ai_lab.sim.deepseek_engine import DeepSeekGameEngine
        from commander_ai_lab.sim.rules import enrich_card

        state.log_lines.append('[DeepSeek Batch] Initializing DeepSeek brain...')
        brain = _get_deepseek_brain()
        if brain and not brain._connected:
            brain.check_connection()
        if not brain or not brain._connected:
            state.error = 'DeepSeek LLM not connected. Go to Simulator > DeepSeek and connect first.'
            state.running = False
            return

        state.log_lines.append(f'[DeepSeek Batch] Connected to {brain.config.model}')

        # Load all decks
        # ── Look up historical win rates from past batch results ──
        deck_win_rates = {}  # deck_name -> float (0-100)
        try:
            results_dir = CFG.results_dir
            if os.path.isdir(results_dir):
                for fname in sorted(os.listdir(results_dir), reverse=True):
                    if fname.startswith('batch-') and fname.endswith('.json'):
                        try:
                            with open(os.path.join(results_dir, fname), 'r') as rf:
                                past = json.loads(rf.read())
                            for dd in past.get('decks', []):
                                dname = dd.get('deckName', '')
                                wr = dd.get('winRate')
                                if dname and wr is not None and dname not in deck_win_rates:
                                    deck_win_rates[dname] = float(wr)
                        except Exception:
                            pass
        except Exception:
            pass

        loaded_decks = {}
        deck_meta = {}  # deck_name -> {commander_name, color_identity, archetype}
        for dn in deck_names:
            raw_cards = _load_deck_cards_by_name(dn)
            if not raw_cards:
                state.log_lines.append(f'[DeepSeek Batch] WARNING: Could not load deck "{dn}", skipping.')
                continue

            # Detect commander and color identity from card data
            commander_name = ''
            color_identity_set = set()
            deck_objs = []
            for cd in raw_cards:
                c = Card(name=cd['name'])
                if cd.get('type_line'): c.type_line = cd['type_line']
                if cd.get('cmc'): c.cmc = float(cd['cmc'])
                if cd.get('power') and cd.get('toughness'):
                    c.power = str(cd['power'])
                    c.toughness = str(cd['toughness'])
                    c.pt = c.power + '/' + c.toughness
                if cd.get('oracle_text'): c.oracle_text = cd['oracle_text']
                if cd.get('mana_cost'): c.mana_cost = cd['mana_cost']
                if cd.get('keywords'):
                    kw = cd['keywords']
                    if isinstance(kw, str):
                        try: kw = json.loads(kw)
                        except Exception: kw = []
                    if isinstance(kw, list): c.keywords = kw
                # Set is_commander flag from DB data
                if cd.get('is_commander'):
                    c.is_commander = True
                    commander_name = cd['name']
                # Collect color identity
                ci_str = cd.get('color_identity', '')
                if ci_str:
                    try:
                        ci_parsed = json.loads(ci_str) if isinstance(ci_str, str) else ci_str
                        if isinstance(ci_parsed, list):
                            for color in ci_parsed:
                                color_identity_set.add(color)
                    except Exception:
                        pass
                enrich_card(c)
                deck_objs.append(c)

            # Infer archetype from deck composition
            creature_count = sum(1 for c in deck_objs if c.is_creature())
            removal_count = sum(1 for c in deck_objs if c.is_removal)
            ramp_count = sum(1 for c in deck_objs if c.is_ramp)
            avg_cmc = sum(c.cmc or 0 for c in deck_objs if not c.is_land()) / max(sum(1 for c in deck_objs if not c.is_land()), 1)
            oracle_all = ' '.join((c.oracle_text or '').lower() for c in deck_objs)
            has_combo_text = any(kw in oracle_all for kw in ['you win the game', 'infinite', 'extra turn'])

            if has_combo_text:
                archetype = 'combo'
            elif creature_count >= 30 and avg_cmc <= 2.8:
                archetype = 'aggro'
            elif removal_count >= 10 or (creature_count <= 18 and avg_cmc >= 3.2):
                archetype = 'control'
            else:
                archetype = 'midrange'

            color_identity_list = sorted(list(color_identity_set))
            deck_meta[dn] = {
                'commander_name': commander_name,
                'color_identity': color_identity_list,
                'archetype': archetype,
                'win_rate': deck_win_rates.get(dn),
            }

            loaded_decks[dn] = deck_objs
            cmdr_info = f' (Commander: {commander_name})' if commander_name else ''
            wr_info = f' [History: {deck_win_rates[dn]:.0f}% WR]' if dn in deck_win_rates else ''
            state.log_lines.append(f'[DeepSeek Batch] Loaded deck "{dn}" ({len(deck_objs)} cards, {archetype}){cmdr_info}{wr_info}')

        if not loaded_decks:
            state.error = 'No decks could be loaded.'
            state.running = False
            return

        # Build matchup schedule: each deck plays num_games vs DeepSeek AI
        deck_list = list(loaded_decks.keys())
        games_per_deck = max(1, num_games // len(deck_list))
        total_games = games_per_deck * len(deck_list)
        state.total_games = total_games

        state.log_lines.append(f'[DeepSeek Batch] Running {games_per_deck} games per deck \u00d7 {len(deck_list)} decks = {total_games} total')

        engine = DeepSeekGameEngine(
            brain=brain,
            ai_player_index=0,  # AI pilots deck_a (user's deck) with full intelligence
            max_turns=25,
            record_log=True,
            ml_log=True,
        )

        start_time = time.time()
        all_deck_results = []
        completed = 0

        for deck_name in deck_list:
            deck_a = loaded_decks[deck_name]
            # Generate a training opponent for each game
            from commander_ai_lab.lab.experiments import _generate_training_deck

            deck_stats = {
                'deckName': deck_name,
                'wins': 0, 'losses': 0, 'totalGames': games_per_deck,
                'totalTurns': 0, 'totalDamageDealt': 0, 'totalDamageReceived': 0,
                'totalSpellsCast': 0, 'totalCreaturesPlayed': 0,
                'games': [],
            }

            meta = deck_meta.get(deck_name, {})
            dk_archetype = meta.get('archetype', 'midrange')
            dk_commander = meta.get('commander_name', '')
            dk_colors = meta.get('color_identity', [])
            dk_win_rate = meta.get('win_rate')

            for g in range(games_per_deck):
                try:
                    deck_b = _generate_training_deck()
                    game_id = f'ds-{state.batch_id}-{deck_name[:12]}-g{g+1}'
                    result = engine.run(
                        deck_a, deck_b,
                        name_a=deck_name + ' (AI)',
                        name_b='Training Opponent',
                        game_id=game_id, archetype=dk_archetype,
                        commander_name=dk_commander,
                        color_identity=dk_colors,
                        win_rate=dk_win_rate,
                    )
                    gd = result.to_dict()
                    gd['gameNumber'] = g + 1
                    deck_stats['games'].append(gd)

                    if result.winner == 0:
                        deck_stats['wins'] += 1
                    else:
                        deck_stats['losses'] += 1
                    deck_stats['totalTurns'] += result.turns
                    if result.player_a_stats:
                        deck_stats['totalDamageDealt'] += result.player_a_stats.damage_dealt
                        deck_stats['totalDamageReceived'] += result.player_a_stats.damage_received
                        deck_stats['totalSpellsCast'] += result.player_a_stats.spells_cast
                        deck_stats['totalCreaturesPlayed'] += result.player_a_stats.creatures_played

                    state.log_lines.append(
                        f'[Game {completed + 1}/{total_games}] {deck_name} (AI-piloted) \u2192 '
                        f'{"WIN" if result.winner == 0 else "LOSS"} (turn {result.turns})'
                    )
                except Exception as ge:
                    state.log_lines.append(f'[Game {completed + 1}/{total_games}] ERROR: {ge}')
                    deck_stats['games'].append({'error': str(ge), 'gameNumber': g + 1})

                completed += 1
                state.completed_games = completed

            n = deck_stats['totalGames']
            deck_stats['winRate'] = round(deck_stats['wins'] / n * 100, 1) if n > 0 else 0.0
            deck_stats['avgTurns'] = round(deck_stats['totalTurns'] / n, 1) if n > 0 else 0.0
            deck_stats['avgDamageDealt'] = round(deck_stats['totalDamageDealt'] / n, 1) if n > 0 else 0.0
            deck_stats['avgDamageReceived'] = round(deck_stats['totalDamageReceived'] / n, 1) if n > 0 else 0.0
            deck_stats['avgSpellsCast'] = round(deck_stats['totalSpellsCast'] / n, 1) if n > 0 else 0.0
            deck_stats['avgCreaturesPlayed'] = round(deck_stats['totalCreaturesPlayed'] / n, 1) if n > 0 else 0.0
            # Include deck intelligence metadata
            deck_stats['archetype'] = dk_archetype
            deck_stats['commander'] = dk_commander
            deck_stats['colorIdentity'] = dk_colors
            if dk_win_rate is not None:
                deck_stats['priorWinRate'] = dk_win_rate
            all_deck_results.append(deck_stats)

        elapsed = time.time() - start_time
        ds_stats = brain.get_stats() if brain else {}

        # Build result in compatible format
        batch_result = {
            'metadata': {
                'batchId': state.batch_id,
                'timestamp': _datetime.now().isoformat(),
                'completedGames': completed,
                'threads': 1,
                'elapsedMs': int(elapsed * 1000),
                'engine': 'deepseek',
                'model': brain.config.model if brain else 'unknown',
            },
            'decks': all_deck_results,
            'deepseekStats': ds_stats,
        }

        # Write ML decision JSONL for the training pipeline
        ml_decisions = engine.flush_ml_decisions()
        if ml_decisions:
            ml_jsonl_path = os.path.join(CFG.results_dir, f'ml-decisions-ds-{state.batch_id}.jsonl')
            os.makedirs(os.path.dirname(ml_jsonl_path) or '.', exist_ok=True)
            with open(ml_jsonl_path, 'w', encoding='utf-8') as mf:
                for dec in ml_decisions:
                    mf.write(json.dumps(dec) + '\n')
            state.log_lines.append(f'[ML Data] Wrote {len(ml_decisions)} decision snapshots to {os.path.basename(ml_jsonl_path)}')
        else:
            state.log_lines.append('[ML Data] No decision snapshots captured (0 decisions)')

        # Save to results dir
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(batch_result, f, indent=2, default=str)

        state.result_path = output_path
        elapsed_ms = int(elapsed * 1000)
        state.elapsed_ms = elapsed_ms
        state.running = False
        state.completed_games = total_games

        state.log_lines.append(f'[DeepSeek Batch] Complete: {completed} games in {elapsed:.1f}s')
        for ds in all_deck_results:
            state.log_lines.append(f'  {ds["deckName"]}: {ds["wins"]}W-{ds["losses"]}L ({ds["winRate"]}% WR)')

        log_sim.info(f'Batch {state.batch_id} complete: {completed} games in {elapsed:.1f}s')

    except Exception as e:
        import traceback
        state.error = str(e)
        state.running = False
        state.log_lines.append(f'[DeepSeek Batch] FATAL: {e}')
        traceback.print_exc()