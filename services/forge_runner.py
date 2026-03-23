"""Forge batch simulation runner: Java discovery, command building, process management."""
import asyncio
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

# ── Global watchdog: single thread monitors all active batches ──
_watchdog_registry: dict[str, dict] = {}   # batch_id -> {state, proc, last_activity}
_watchdog_lock = threading.Lock()
_watchdog_started = False
_STALL_LIMIT = 600  # 10 min

def _global_watchdog_loop():
    """Single daemon thread that checks all active batches for stalls."""
    while True:
        time.sleep(5)
        with _watchdog_lock:
            finished = []
            for bid, entry in _watchdog_registry.items():
                proc = entry["proc"]
                if proc.poll() is not None:
                    finished.append(bid)
                    continue
                if (time.monotonic() - entry["last_activity"]) > _STALL_LIMIT:
                    log.warning(f"Stall detected for batch {bid}, killing process")
                    entry["state"].log_lines.append("[WATCHDOG] Process stalled. Killed.")
                    proc.kill()
                    entry["state"].running = False
                    entry["state"].error = "Stall detected (10 min no output)"
                    finished.append(bid)
            for bid in finished:
                del _watchdog_registry[bid]

def _ensure_watchdog_started():
    global _watchdog_started
    if not _watchdog_started:
        with _watchdog_lock:
            if not _watchdog_started:
                t = threading.Thread(target=_global_watchdog_loop, daemon=True)
                t.start()
                _watchdog_started = True

def _register_batch(batch_id: str, state, proc):
    _ensure_watchdog_started()
    with _watchdog_lock:
        _watchdog_registry[batch_id] = {
            "state": state, "proc": proc, "last_activity": time.monotonic()
        }

def _touch_batch(batch_id: str):
    with _watchdog_lock:
        if batch_id in _watchdog_registry:
            _watchdog_registry[batch_id]["last_activity"] = time.monotonic()

def _unregister_batch(batch_id: str):
    with _watchdog_lock:
        _watchdog_registry.pop(batch_id, None)


# ── Java 17 Discovery ───────────────────────────────────────────────

# Ordered list of directories to scan for JDK 17 installations.
# Covers: Eclipse Temurin, Oracle, Amazon Corretto, Microsoft, Azul Zulu, SAP.
_JAVA17_SEARCH_DIRS = [
    r'C:\Program Files\Eclipse Adoptium',
    r'C:\Program Files\Java',
    r'C:\Program Files\Amazon Corretto',
    r'C:\Program Files\Microsoft',
    r'C:\Program Files\Zulu',
    r'C:\Program Files\BellSoft',
    r'C:\Program Files\SapMachine',
]


def _find_java17() -> str:
    """
    Search well-known JDK install directories for a Java 17 binary.
    Falls back to JAVA17_HOME env var, then JAVA_HOME, then warns and returns 'java'.
    Returns the absolute path to java.exe if found, otherwise 'java'.
    """
    # 1. Explicit override via env var
    env_override = os.environ.get('JAVA17_HOME', '').strip()
    if env_override:
        candidate = os.path.join(env_override, 'bin', 'java.exe')
        if os.path.isfile(candidate):
            log.info(f"Java 17 found via JAVA17_HOME: {candidate}")
            return candidate
        log.warning(f"JAVA17_HOME set to '{env_override}' but java.exe not found there.")

    # 2. Scan vendor directories
    for d in _JAVA17_SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            children = os.listdir(d)
        except OSError:
            continue
        for child in sorted(children):  # sorted = deterministic, picks lowest 17.x
            if re.match(r'jdk-?17', child, re.IGNORECASE) or re.match(r'temurin-17', child, re.IGNORECASE):
                candidate = os.path.join(d, child, 'bin', 'java.exe')
                if os.path.isfile(candidate):
                    log.info(f"Java 17 found: {candidate}")
                    return candidate

    # 3. JAVA_HOME fallback — only accept if it IS version 17
    java_home = os.environ.get('JAVA_HOME', '').strip()
    if java_home:
        candidate = os.path.join(java_home, 'bin', 'java.exe')
        if os.path.isfile(candidate):
            try:
                result = subprocess.run(
                    [candidate, '-version'],
                    capture_output=True, text=True, timeout=5
                )
                version_output = result.stderr or result.stdout
                if 'version "17' in version_output:
                    log.info(f"Java 17 found via JAVA_HOME: {candidate}")
                    return candidate
                else:
                    log.warning(
                        f"JAVA_HOME points to '{java_home}' but it is not Java 17. "
                        f"Version output: {version_output.strip()!r}"
                    )
            except Exception as e:
                log.warning(f"Could not probe JAVA_HOME java version: {e}")

    # 4. Nothing found — warn loudly so the log surfaces the issue
    log.error(
        "Java 17 not found! Forge simulation requires Java 17. "
        "Install Eclipse Temurin 17 (winget install EclipseAdoptium.Temurin.17.JDK) "
        "or set the JAVA17_HOME environment variable to your JDK 17 install directory. "
        "Falling back to system 'java' which may be the wrong version."
    )
    return 'java'


_JAVA17_PATH = None


def get_java17() -> str:
    global _JAVA17_PATH
    if _JAVA17_PATH is None:
        _JAVA17_PATH = _find_java17()
    return _JAVA17_PATH


def reset_java17_cache():
    """Force re-discovery of Java 17 path (useful after installing JDK at runtime)."""
    global _JAVA17_PATH
    _JAVA17_PATH = None


def build_java_command(
    decks: list, num_games: int, threads: int, seed: Optional[int],
    clock: int, output_path: str, use_learned_policy: bool = False,
    policy_server: str = "http://localhost:8080", policy_style: str = "midrange",
    policy_greedy: bool = False, ai_simplified: bool = False,
    ai_think_time_ms: int = -1, max_queue_depth: int = -1,
) -> list:
    java17 = get_java17()
    lab_jar = CFG.lab_jar
    forge_jar = CFG.forge_jar
    forge_dir = CFG.forge_dir
    if not lab_jar or not os.path.isfile(lab_jar):
        log.error(f"Lab JAR not found at '{lab_jar}'. Run 'mvn package' first.")
        raise FileNotFoundError(f"Lab JAR not found: {lab_jar}")
    cmd = [
        java17, '-jar', lab_jar,
        '--forge-jar', forge_jar,
        '--forge-dir', forge_dir,
        '--games', str(num_games),
        '--threads', str(threads),
        '--clock', str(clock),
        '--output', output_path,
    ]
    # Map deck list to --deck1 .. --deck4
    for i, d in enumerate(decks[:4], start=1):
        cmd += [f'--deck{i}', str(d)]
    if seed is not None:
        cmd += ['--seed', str(seed)]
    if use_learned_policy:
        cmd += ['--policy', policy_style, '--policyServer', policy_server]
        if policy_greedy:
            cmd += ['--policyGreedy']
    if ai_simplified:
        cmd += ['--aiSimplified']
    if ai_think_time_ms > 0:
        cmd += ['--aiThinkTimeMs', str(ai_think_time_ms)]
    if max_queue_depth > 0:
        cmd += ['--maxQueueDepth', str(max_queue_depth)]
    return cmd


def _run_process_blocking(state: BatchState, cmd: list):
    """Run Forge subprocess, parse progress, generate deck reports."""
    log.info(f"Running: {' '.join(cmd)}")

    # Ensure Forge subprocesses use Java 17
    env = os.environ.copy()
    java17 = get_java17()
    if java17 != 'java':
        java17_bin = os.path.dirname(java17)
        java17_home = os.path.dirname(java17_bin)
        env['JAVA_HOME'] = java17_home
        env['PATH'] = java17_bin + os.pathsep + env.get('PATH', '')

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        state.process = proc
    except Exception as e:
        state.running = False
        state.error = str(e)
        log.error(f"Failed to start subprocess: {e}")
        return

    _register_batch(state.batch_id, state, proc)

    for line in proc.stdout:
        _touch_batch(state.batch_id)
        line = line.rstrip()
        state.log_lines.append(line)
        gm = re.match(r'\[Game (\d+)/(\d+)\]', line)
        if gm:
            state.completed_games = int(gm.group(1))
            state.total_games = int(gm.group(2))
        pm = re.match(r'\[PROGRESS\].*?(\d+\.?\d*)\s*sims/sec', line)
        if pm:
            state.sims_per_sec = float(pm.group(1))

    proc.wait()
    _unregister_batch(state.batch_id)
    elapsed = (_datetime.now() - state.start_time).total_seconds() * 1000
    state.elapsed_ms = int(elapsed)
    if proc.returncode != 0:
        state.running = False
        # Include last few log lines in error for easier diagnosis
        tail = '  |  '.join(state.log_lines[-5:]) if state.log_lines else '(no output)'
        state.error = f"Exit code {proc.returncode} — last output: {tail}"
    else:
        state.running = False
        state.completed_games = state.total_games


async def run_batch_subprocess(
    state: BatchState,
    decks: list,
    num_games: int,
    threads: int,
    seed: Optional[int] = None,
    clock: int = 6000,
    output_path: str = "results",
    use_learned_policy: bool = False,
    policy_style: str = "midrange",
    policy_greedy: bool = False,
    ai_simplified: bool = False,
    ai_think_time_ms: int = -1,
    max_queue_depth: int = -1,
):
    """Async wrapper that runs Forge subprocess in executor."""
    try:
        policy_server = f"http://localhost:{CFG.port}"
        cmd = build_java_command(
            decks, num_games, threads, seed, clock, output_path,
            use_learned_policy=use_learned_policy,
            policy_server=policy_server,
            policy_style=policy_style,
            policy_greedy=policy_greedy,
            ai_simplified=ai_simplified,
            ai_think_time_ms=ai_think_time_ms,
            max_queue_depth=max_queue_depth,
        )
        log.info(f"Starting batch {state.batch_id}: {' '.join(cmd[:6])}...")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run_process_blocking, state, cmd)
    except Exception as e:
        state.error = str(e)
        state.running = False
        log.error(f"Batch {state.batch_id} ERROR: {e}")


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
                    cfg = DeepSeekConfig(
                        api_base=os.environ.get("BRAIN_API_BASE", "http://localhost:11434"),
                        model=os.environ.get("BRAIN_MODEL", "gpt-oss:20b"),
                        temperature=float(os.environ.get("BRAIN_TEMPERATURE", "0.3")),
                        max_tokens=int(os.environ.get("BRAIN_MAX_TOKENS", "1024")),
                        request_timeout=float(os.environ.get("BRAIN_TIMEOUT", "300.0")),
                    )
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

        deck_win_rates = {}
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
        deck_meta = {}
        for dn in deck_names:
            raw_cards = _load_deck_cards_by_name(dn)
            if not raw_cards:
                state.log_lines.append(f'[DeepSeek Batch] WARNING: Could not load deck "{dn}", skipping.')
                continue

            commander_name = ''
            color_identity_set = set()
            deck_objs = []
            for cd in raw_cards:
                c = Card(name=(cd.get('card_name') or cd.get('name', '')))
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
                if cd.get('is_commander'):
                    c.is_commander = True
                    commander_name = (cd.get('card_name') or cd.get('name', ''))
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

        deck_list = list(loaded_decks.keys())
        games_per_deck = max(1, num_games // len(deck_list))
        total_games = games_per_deck * len(deck_list)
        state.total_games = total_games

        state.log_lines.append(f'[DeepSeek Batch] Running {games_per_deck} games per deck \u00d7 {len(deck_list)} decks = {total_games} total')

        engine = DeepSeekGameEngine(
            brain=brain,
            ai_player_index=0,
            max_turns=25,
            record_log=True,
            ml_log=True,
        )

        start_time = time.time()
        all_deck_results = []
        completed = 0

        for deck_name in deck_list:
            deck_a = loaded_decks[deck_name]
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
            deck_stats['archetype'] = dk_archetype
            deck_stats['commander'] = dk_commander
            deck_stats['colorIdentity'] = dk_colors
            if dk_win_rate is not None:
                deck_stats['priorWinRate'] = dk_win_rate
            all_deck_results.append(deck_stats)

        elapsed = time.time() - start_time
        ds_stats = brain.get_stats() if brain else {}

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

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(batch_result, f, indent=2, default=str)

        state.result_path = output_path
        state.elapsed_ms = int(elapsed * 1000)
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
