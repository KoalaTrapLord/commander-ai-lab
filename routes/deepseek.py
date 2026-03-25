"""
routes/deepseek.py
==================
Python simulator & DeepSeek AI opponent endpoints:
  POST /api/sim/run
  GET  /api/sim/status
  GET  /api/sim/result
  POST /api/sim/run-from-deck
  POST /api/sim/run-deepseek
  POST /api/deepseek/connect
  GET  /api/deepseek/status
  POST /api/deepseek/configure
  GET  /api/deepseek/logs
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import threading as _threading
import traceback
import uuid as _uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi import Request as FastAPIRequest
from fastapi.responses import JSONResponse

from models.state import CFG
from services.database import _get_db_conn
from services.forge_runner import _get_deepseek_brain
from services.logging import log_sim, _ml_logging_enabled
from commander_ai_lab.sim.validator_brain import ValidatorBrain, ValidatorConfig
logger = logging.getLogger(__name__)

router = APIRouter(tags=["deepseek"])

# In-memory store for simulation runs
_sim_runs = {}  # sim_id -> { status, result, error }
_sim_lock = _threading.Lock()

# ── Validator singleton ──
_validator_brain: ValidatorBrain | None = None
_validator_lock = _threading.Lock()


def _get_validator_brain() -> ValidatorBrain | None:
    global _validator_brain
    if os.environ.get("VALIDATOR_ENABLED", "false").lower() != "true":
        return None
    with _validator_lock:
        if _validator_brain is None:
            cfg = ValidatorConfig(
                api_base=os.environ.get("VALIDATOR_API_BASE", "http://localhost:11434"),
                model=os.environ.get("VALIDATOR_MODEL", "deepseek-r1:8b"),
                max_tokens=int(os.environ.get("VALIDATOR_MAX_TOKENS", "2048")),
                request_timeout=float(os.environ.get("VALIDATOR_TIMEOUT", "300.0")),
            )
            _validator_brain = ValidatorBrain(cfg)
    return _validator_brain

# ══════════════════════════════════════════════════════════════
# Shared Helpers (extracted to deduplicate sim threads — #42)
# ══════════════════════════════════════════════════════════════

_SRC_PATH_ADDED = False


def _ensure_src_path():
    """Add project src/ to sys.path once."""
    global _SRC_PATH_ADDED
    if not _SRC_PATH_ADDED:
        src_dir = str(Path(__file__).resolve().parent.parent / 'src')
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        _SRC_PATH_ADDED = True


def _build_deck_from_card_data(card_data: list[dict]) -> list:
    """Build a list of Card objects from DB card dicts. Used by v2 + deepseek threads."""
    _ensure_src_path()
    from commander_ai_lab.sim.models import Card
    from commander_ai_lab.sim.rules import enrich_card

    deck = []
    for cd in card_data:
        c = Card(name=cd['name'])
        if cd.get('type_line'):
            c.type_line = cd['type_line']
        if cd.get('cmc'):
            c.cmc = float(cd['cmc'])
        if cd.get('power') and cd.get('toughness'):
            c.power = str(cd['power'])
            c.toughness = str(cd['toughness'])
            c.pt = c.power + '/' + c.toughness
        if cd.get('oracle_text'):
            c.oracle_text = cd['oracle_text']
        if cd.get('mana_cost'):
            c.mana_cost = cd['mana_cost']
        if cd.get('keywords'):
            kw = cd['keywords']
            if isinstance(kw, str):
                try:
                    kw = json.loads(kw)
                except Exception:
                    kw = []
            if isinstance(kw, list):
                c.keywords = kw
        enrich_card(c)
        deck.append(c)
    return deck


def _run_game_loop(engine, deck_a, deck_b, deck_name, opponent_name,
                   num_games, sim_id, **run_kwargs):
    """Run *num_games* and accumulate stats. Returns (game_results, stats, elapsed)."""
    start = time.time()
    wins = losses = total_turns = 0
    total_damage_dealt = total_damage_received = 0
    total_spells_cast = total_creatures_played = 0
    total_removal_used = total_ramp_played = 0
    total_cards_drawn = total_max_board = 0
    game_results = []

    for i in range(num_games):
        kw = dict(run_kwargs)
        # DeepSeek engine needs per-game IDs
        if 'game_id_prefix' in kw:
            prefix = kw.pop('game_id_prefix')
            kw['game_id'] = f'{prefix}-g{i+1}'
        result = engine.run(deck_a, deck_b, name_a=deck_name,
                            name_b=opponent_name, **kw)
        game_data = result.to_dict()
        game_data['gameNumber'] = i + 1
              # Phase 8: Surface player_explanation from validation in turn log
        for turn_entry in game_data.get('log', []):
            v = turn_entry.get('validation')
            if isinstance(v, dict) and v.get('player_explanation'):
                turn_entry['player_explanation'] = v['player_explanation']
        game_results.append(game_data)

        if result.winner == 0:
            wins += 1
        else:
            losses += 1
        total_turns += result.turns

        if result.player_a_stats:
            s = result.player_a_stats
            total_damage_dealt += s.damage_dealt
            total_damage_received += s.damage_received
            total_spells_cast += s.spells_cast
            total_creatures_played += s.creatures_played
            total_removal_used += s.removal_used
            total_ramp_played += s.ramp_played
            total_cards_drawn += s.cards_drawn
            total_max_board += s.max_board_size

        with _sim_lock:
            _sim_runs[sim_id]['completed'] = i + 1

    elapsed = time.time() - start
    stats = dict(
        wins=wins, losses=losses, total_turns=total_turns,
        total_damage_dealt=total_damage_dealt,
        total_damage_received=total_damage_received,
        total_spells_cast=total_spells_cast,
        total_creatures_played=total_creatures_played,
        total_removal_used=total_removal_used,
        total_ramp_played=total_ramp_played,
        total_cards_drawn=total_cards_drawn,
        total_max_board=total_max_board,
    )
    return game_results, stats, elapsed


def _build_summary(stats: dict, deck_name: str, opponent_name: str,
                   num_games: int, elapsed: float, **extra) -> dict:
    """Build the JSON-serialisable summary dict from accumulated stats."""
    n = num_games
    summary = {
        'deckName': deck_name,
        'opponentName': opponent_name,
        'totalGames': n,
        'wins': stats['wins'],
        'losses': stats['losses'],
        'winRate': round(stats['wins'] / n * 100, 1) if n > 0 else 0.0,
        'avgTurns': round(stats['total_turns'] / n, 1) if n > 0 else 0.0,
        'avgDamageDealt': round(stats['total_damage_dealt'] / n, 1) if n > 0 else 0.0,
        'avgDamageReceived': round(stats['total_damage_received'] / n, 1) if n > 0 else 0.0,
        'avgSpellsCast': round(stats['total_spells_cast'] / n, 1) if n > 0 else 0.0,
        'avgCreaturesPlayed': round(stats['total_creatures_played'] / n, 1) if n > 0 else 0.0,
        'avgRemovalUsed': round(stats['total_removal_used'] / n, 1) if n > 0 else 0.0,
        'avgRampPlayed': round(stats['total_ramp_played'] / n, 1) if n > 0 else 0.0,
        'avgCardsDrawn': round(stats['total_cards_drawn'] / n, 1) if n > 0 else 0.0,
        'avgMaxBoardSize': round(stats['total_max_board'] / n, 1) if n > 0 else 0.0,
        'elapsedSeconds': round(elapsed, 3),
    }
    summary.update(extra)
    return summary


def _finish_sim(sim_id, summary, game_results, engine=None):
    """Mark a sim run as complete."""
    with _sim_lock:
        _sim_runs[sim_id]['status'] = 'complete'
        _sim_runs[sim_id]['result'] = {'summary': summary, 'games': game_results}

          # --- Persist ml-decision-*.json for coach / training dashboard ---
    try:
        deck_name = summary.get('deckName', 'Unknown')
        opponent_name = summary.get('opponentName', 'Training Deck')
        batch_data = {
            'format': 'python-sim',
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'simId': sim_id,
            'decks': [
                {
                    'deckName': deck_name,
                    'seatIndex': 0,
                    'commanderName': summary.get('commanderName', ''),
                    'colorIdentity': summary.get('colorIdentity', []),
                    'games': game_results,
                },
                {
                    'deckName': opponent_name,
                    'seatIndex': 1,
                    'commanderName': '',
                    'colorIdentity': [],
                },
            ],
            'summary': summary,
        }
        results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
        os.makedirs(results_dir, exist_ok=True)
        batch_path = os.path.join(results_dir, f'ml-decision-sim-{sim_id}.json')
        with open(batch_path, 'w') as f:
            json.dump(batch_data, f, indent=2, default=str)
        logger.info(f'Saved batch results to {batch_path}')

        # Auto-generate deck report for training dashboard / coach
        try:
            from coach.report_generator import generate_deck_reports
            reports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deck-reports')
            os.makedirs(reports_dir, exist_ok=True)
            generate_deck_reports(str(results_dir), str(reports_dir))
            logger.info(f'Generated deck reports after sim {sim_id}')
        except ImportError:
            logger.warning('reports module not available; skipping deck report generation')
        except Exception as e:
            logger.warning(f'Could not generate deck report: {e}')
    except Exception as e:
        logger.error(f'Failed to persist sim results: {e}')

    # --- Flush ML decisions JSONL for training pipeline ---
    # NOTE: DeepSeek thread flushes manually before calling _finish_sim(engine=None)
    # to avoid a double-flush that would produce an empty .jsonl file.
    if engine is not None and hasattr(engine, 'flush_ml_decisions'):
        ml_decisions = engine.flush_ml_decisions()
        if ml_decisions:
            ml_path = os.path.join('results', f'ml-decisions-sim-{sim_id[:8]}.jsonl')
            os.makedirs('results', exist_ok=True)
            with open(ml_path, 'w', encoding='utf-8') as mf:
                for dec in ml_decisions:
                    mf.write(json.dumps(dec) + '\n')
            logger.info(f'Wrote {len(ml_decisions)} ML decisions to {ml_path}')
        
def _fail_sim(sim_id, error):
    """Mark a sim run as errored."""
    with _sim_lock:
        _sim_runs[sim_id]['status'] = 'error'
        _sim_runs[sim_id]['error'] = str(error)

# ══════════════════════════════════════════════════════════════
# Background Sim Threads (now thin wrappers around shared helpers)
# ══════════════════════════════════════════════════════════════

def _run_sim_thread(sim_id: str, decklist: list, num_games: int,
                    deck_name: str, record_logs: bool):
    """Background thread: basic Monte Carlo sim from a raw decklist."""
    try:
        _ensure_src_path()
        from commander_ai_lab.sim.engine import GameEngine
        from commander_ai_lab.lab.experiments import build_deck, _generate_training_deck

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        deck_a = build_deck(decklist)
        deck_b = _generate_training_deck()
        engine = GameEngine(max_turns=25, record_log=record_logs, ml_log=True)

        game_results, stats, elapsed = _run_game_loop(
            engine, deck_a, deck_b, deck_name, 'Training Deck',
            num_games, sim_id)

        summary = _build_summary(stats, deck_name, 'Training Deck',
                                 num_games, elapsed)
        _finish_sim(sim_id, summary, game_results, engine=engine)
    except Exception as e:
        _fail_sim(sim_id, e)
        traceback.print_exc()


def _run_sim_thread_v2(sim_id: str, card_data: list[dict], num_games: int,
                       deck_name: str, record_logs: bool):
    """Background thread: sim with full card data from the DB."""
    try:
        _ensure_src_path()
        from commander_ai_lab.sim.engine import GameEngine
        from commander_ai_lab.lab.experiments import _generate_training_deck

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        deck_a = _build_deck_from_card_data(card_data)
        deck_b = _generate_training_deck()
        engine = GameEngine(max_turns=25, record_log=record_logs, ml_log=True)

        game_results, stats, elapsed = _run_game_loop(
            engine, deck_a, deck_b, deck_name, 'Training Deck',
            num_games, sim_id)

        summary = _build_summary(stats, deck_name, 'Training Deck',
                                 num_games, elapsed)
        _finish_sim(sim_id, summary, game_results, engine=engine)
    except Exception as e:
        _fail_sim(sim_id, e)
        traceback.print_exc()


def _run_sim_thread_deepseek(sim_id: str, card_data: list[dict],
                             num_games: int, deck_name: str,
                             record_logs: bool):
    """Background thread: sim using DeepSeek AI opponent."""
    try:
        _ensure_src_path()
        from commander_ai_lab.sim.deepseek_engine import DeepSeekGameEngine
        from commander_ai_lab.lab.experiments import _generate_training_deck

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        deck_a = _build_deck_from_card_data(card_data)
        deck_b = _generate_training_deck()

        brain = _get_deepseek_brain()
        if brain and not brain._connected:
            brain.check_connection()

        validator = _get_validator_brain()  # None if disabled
        engine = DeepSeekGameEngine(
            brain=brain, ai_player_index=1,
            max_turns=25, record_log=record_logs, ml_log=True,
            validator=validator)

        game_results, stats, elapsed = _run_game_loop(
            engine, deck_a, deck_b, deck_name, 'DeepSeek AI',
            num_games, sim_id,
            game_id_prefix=f'ds-sim-{sim_id[:8]}',
            archetype='midrange')

        # Flush ML decisions once here — pass engine=None to _finish_sim
        # to prevent a second flush that would produce an empty .jsonl file.
        ml_decisions = engine.flush_ml_decisions()
        if ml_decisions and brain and brain._connected:
            ml_path = os.path.join('results',
                                   f'ml-decisions-sim-{sim_id[:8]}.jsonl')
            os.makedirs('results', exist_ok=True)
            with open(ml_path, 'w', encoding='utf-8') as mf:
                for dec in ml_decisions:
                    mf.write(json.dumps(dec) + '\n')
            logger.info(f'[ML Data] Wrote {len(ml_decisions)} decision snapshots to {ml_path}')
                elif ml_decisions and (not brain or not brain._connected):
                              logger.warning(
                f'[ML Data] Skipping {len(ml_decisions)} snapshots for sim {sim_id} — '
                f'brain not connected, all actions are heuristic fallback '
                f'(not useful for supervised training)'
            )
                          else:
            logger.warning(f'[ML Data] No decision snapshots captured for sim {sim_id} (0 decisions)')
                              

        ds_stats = brain.get_stats() if brain else {}
        summary = _build_summary(
            stats, deck_name, 'DeepSeek AI', num_games, elapsed,
            opponentType='deepseek', deepseekStats=ds_stats)
        # engine=None: ML decisions already flushed above — do not flush again
        _finish_sim(sim_id, summary, game_results, engine=None)
    except Exception as e:
        _fail_sim(sim_id, e)
        traceback.print_exc()

# ══════════════════════════════════════════════════════════════
# N-Player Sim Thread
# ══════════════════════════════════════════════════════════════


def _run_sim_thread_n_player(sim_id: str, decks_data: list[list[dict]],
                              deck_names: list[str], num_games: int,
                              record_logs: bool, engine_type: str):
    """Background thread: N-player (2-4) batch simulation."""
    try:
        _ensure_src_path()
        from commander_ai_lab.sim.engine import GameEngine
        from commander_ai_lab.sim.deepseek_engine import DeepSeekGameEngine

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        n_players = len(decks_data)
        built_decks = [_build_deck_from_card_data(cd) for cd in decks_data]

        if engine_type == 'deepseek':
            brain = _get_deepseek_brain()
            if brain and not brain._connected:
                brain.check_connection()
            engine = DeepSeekGameEngine(
                brain=brain, ai_player_index=1,
                max_turns=25, record_log=record_logs, ml_log=True)
        else:
            engine = GameEngine(max_turns=25, record_log=record_logs, ml_log=True)

        # Per-seat accumulators
        seat_wins = [0] * n_players
        seat_turns = [0] * n_players
        seat_damage_dealt = [0] * n_players
        seat_spells_cast = [0] * n_players
        seat_creatures_played = [0] * n_players
        seat_removal_used = [0] * n_players
        seat_ramp_played = [0] * n_players
        seat_cards_drawn = [0] * n_players
        seat_max_board = [0] * n_players

        game_results = []
        start = time.time()

        for i in range(num_games):
            result = engine.run_n(decks=built_decks, names=deck_names)
            game_data = result.to_dict()
            game_data['gameNumber'] = i + 1
            game_results.append(game_data)

            if 0 <= result.winner_seat < n_players:
                seat_wins[result.winner_seat] += 1

            for pr in result.players:
                si = pr.seat_index
                seat_turns[si] += result.turns
                if pr.stats:
                    seat_damage_dealt[si] += pr.stats.damage_dealt
                    seat_spells_cast[si] += pr.stats.spells_cast
                    seat_creatures_played[si] += pr.stats.creatures_played
                    seat_removal_used[si] += pr.stats.removal_used
                    seat_ramp_played[si] += pr.stats.ramp_played
                    seat_cards_drawn[si] += pr.stats.cards_drawn
                    seat_max_board[si] += pr.stats.max_board_size

            with _sim_lock:
                _sim_runs[sim_id]['completed'] = i + 1

        elapsed = time.time() - start
        n = num_games if num_games > 0 else 1

        players_summary = []
        for si in range(n_players):
            players_summary.append({
                'seat': si,
                'deckName': deck_names[si],
                'wins': seat_wins[si],
                'winRate': round(seat_wins[si] / n * 100, 1),
                'avgTurns': round(seat_turns[si] / n, 1),
                'avgDamageDealt': round(seat_damage_dealt[si] / n, 1),
                'avgSpellsCast': round(seat_spells_cast[si] / n, 1),
                'avgCreaturesPlayed': round(seat_creatures_played[si] / n, 1),
                'avgRemovalUsed': round(seat_removal_used[si] / n, 1),
                'avgRampPlayed': round(seat_ramp_played[si] / n, 1),
                'avgCardsDrawn': round(seat_cards_drawn[si] / n, 1),
                'avgMaxBoardSize': round(seat_max_board[si] / n, 1),
            })

        summary = {
            'playerCount': n_players,
            'totalGames': num_games,
            'players': players_summary,
            'elapsedSeconds': round(elapsed, 3),
        }
        _finish_sim(sim_id, summary, game_results, engine=engine)
    except Exception as e:
        _fail_sim(sim_id, e)
        traceback.print_exc()


# ══════════════════════════════════════════════════════════════
# Simulation API Endpoints
# ══════════════════════════════════════════════════════════════


def _create_sim_run(num_games, deck_name):
    """Create a queued sim run entry and return its ID."""
    sim_id = str(_uuid.uuid4())[:8]
    with _sim_lock:
        _sim_runs[sim_id] = {
            'status': 'queued', 'completed': 0,
            'total': num_games, 'deckName': deck_name,
            'result': None, 'error': None,
        }
    return sim_id


def _fetch_deck_card_data(deck_id):
    """Load card data from the DB for a given deck ID. Returns (deck_name, card_data) or raises."""
    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute('SELECT name FROM decks WHERE id = ?', (deck_id,))
    row = cur.fetchone()
    if not row:
        return None, None
    deck_name = row[0]
    cur.execute("""
        SELECT dc.card_name, dc.quantity,
               ce.type_line, ce.cmc, ce.power, ce.toughness,
               ce.oracle_text, ce.keywords, ce.mana_cost
        FROM deck_cards dc
        LEFT JOIN (
            SELECT scryfall_id, type_line, cmc, power, toughness,
                   oracle_text, keywords, mana_cost
            FROM collection_entries GROUP BY scryfall_id
        ) ce ON ce.scryfall_id = dc.scryfall_id
        WHERE dc.deck_id = ?
    """, (deck_id,))
    card_data = []
    for r in cur.fetchall():
        for _ in range(r[1] or 1):
            card_data.append({
                'name': r[0], 'type_line': r[2] or '',
                'cmc': r[3] or 0, 'power': r[4] or '',
                'toughness': r[5] or '', 'oracle_text': r[6] or '',
                'keywords': r[7] or '', 'mana_cost': r[8] or '',
            })
    return deck_name, card_data


@router.post('/api/sim/run')
async def sim_run(request: FastAPIRequest):
    """Start a Monte Carlo simulation with the Python engine."""
    body = await request.json()
    decklist = body.get('decklist', [])
    num_games = body.get('numGames', 10)
    deck_name = body.get('deckName', 'My Deck')
    record_logs = body.get('recordLogs', True)

    if not decklist:
        return JSONResponse({'error': 'decklist is required'}, status_code=400)
    if num_games < 1 or num_games > 1000:
        return JSONResponse({'error': 'numGames must be 1-1000'}, status_code=400)

    sim_id = _create_sim_run(num_games, deck_name)
    _threading.Thread(target=_run_sim_thread,
                      args=(sim_id, decklist, num_games, deck_name, record_logs),
                      daemon=True).start()
    return JSONResponse({'simId': sim_id, 'status': 'queued', 'total': num_games})


@router.get('/api/sim/status')
async def sim_status(simId: str):
    """Poll simulation progress."""
    with _sim_lock:
        run = _sim_runs.get(simId)
    if not run:
        return JSONResponse({'error': 'sim not found'}, status_code=404)
    return JSONResponse({
        'simId': simId, 'status': run['status'],
        'completed': run['completed'], 'total': run['total'],
        'deckName': run.get('deckName', ''), 'error': run.get('error'),
    })


@router.get('/api/sim/result')
async def sim_result(simId: str):
    """Get completed simulation results."""
    with _sim_lock:
        run = _sim_runs.get(simId)
    if not run:
        return JSONResponse({'error': 'sim not found'}, status_code=404)
    if run['status'] != 'complete':
        return JSONResponse({'error': 'sim not complete', 'status': run['status']},
                            status_code=400)
    return JSONResponse(run['result'])


@router.post('/api/sim/run-from-deck')
async def sim_run_from_deck(request: FastAPIRequest):
    """Start simulation using a deck from the Deck Builder (by deck ID)."""
    body = await request.json()
    deck_id = body.get('deckId')
    num_games = body.get('numGames', 10)
    record_logs = body.get('recordLogs', True)

    if not deck_id:
        return JSONResponse({'error': 'deckId required'}, status_code=400)

    deck_name, card_data = _fetch_deck_card_data(deck_id)
    if deck_name is None:
        return JSONResponse({'error': 'deck not found'}, status_code=404)
    if not card_data:
        return JSONResponse({'error': 'deck has no cards'}, status_code=400)

    sim_id = _create_sim_run(num_games, deck_name)
    _threading.Thread(target=_run_sim_thread_v2,
                      args=(sim_id, card_data, num_games, deck_name, record_logs),
                      daemon=True).start()
    return JSONResponse({'simId': sim_id, 'status': 'queued',
                         'total': num_games, 'deckName': deck_name})


@router.post('/api/sim/run-deepseek')
async def sim_run_deepseek(request: FastAPIRequest):
    """Start simulation using DeepSeek AI as the opponent brain."""
    body = await request.json()
    deck_id = body.get('deckId')
    num_games = body.get('numGames', 5)
    record_logs = body.get('recordLogs', True)

    if not deck_id:
        return JSONResponse({'error': 'deckId required'}, status_code=400)
    if num_games < 1 or num_games > 50:
        return JSONResponse({'error': 'numGames must be 1-50 for DeepSeek mode'},
                            status_code=400)

    deck_name, card_data = _fetch_deck_card_data(deck_id)
    if deck_name is None:
        return JSONResponse({'error': 'deck not found'}, status_code=404)
    if not card_data:
        return JSONResponse({'error': 'deck has no cards'}, status_code=400)

    sim_id = _create_sim_run(num_games, deck_name)
    _threading.Thread(target=_run_sim_thread_deepseek,
                      args=(sim_id, card_data, num_games, deck_name, record_logs),
                      daemon=True).start()
    return JSONResponse({'simId': sim_id, 'status': 'queued',
                         'total': num_games, 'deckName': deck_name,
                         'opponentType': 'deepseek'})


@router.post('/api/sim/run-n-player')
async def sim_run_n_player(request: FastAPIRequest):
    """Start an N-player (2-4) batch simulation."""
    body = await request.json()
    deck_ids = body.get('deckIds', [])
    num_games = body.get('numGames', 10)
    record_logs = body.get('recordLogs', True)
    engine_type = body.get('engineType', 'heuristic')

    if len(deck_ids) < 2 or len(deck_ids) > 4:
        return JSONResponse({'error': '2-4 decks required'}, status_code=400)
    if num_games < 1 or num_games > 1000:
        return JSONResponse({'error': 'numGames must be 1-1000'}, status_code=400)

    decks_data = []
    deck_names = []
    for did in deck_ids:
        name, cards = _fetch_deck_card_data(did)
        if name is None:
            return JSONResponse({'error': f'Deck {did} not found'}, status_code=404)
        if not cards:
            return JSONResponse({'error': f'Deck {did} has no cards'}, status_code=400)
        deck_names.append(name)
        decks_data.append(cards)

    sim_id = _create_sim_run(num_games, ' vs '.join(deck_names))
    _threading.Thread(target=_run_sim_thread_n_player,
                      args=(sim_id, decks_data, deck_names, num_games,
                            record_logs, engine_type),
                      daemon=True).start()
    return JSONResponse({
        'simId': sim_id, 'status': 'queued', 'total': num_games,
        'deckNames': deck_names, 'playerCount': len(deck_ids),
    })


# ══════════════════════════════════════════════════════════════
# DeepSeek AI Brain Endpoints
# ══════════════════════════════════════════════════════════════


@router.post('/api/deepseek/connect')
async def deepseek_connect(request: FastAPIRequest):
    """Test connection to the DeepSeek LLM endpoint and auto-detect model."""
    body = await request.json() if await request.body() else {}
    api_base = body.get('apiBase', None)
    model = body.get('model', None)

    brain = _get_deepseek_brain()
    if brain is None:
        return JSONResponse({'error': 'DeepSeek brain failed to initialize'},
                            status_code=500)

    if api_base:
        brain.config.api_base = api_base
    if model:
        brain.config.model = model

    connected = brain.check_connection()
    return JSONResponse({
        'connected': connected,
        'apiBase': brain.config.api_base,
        'model': brain.config.model,
        'stats': brain.get_stats(),
    })


@router.get('/api/deepseek/status')
async def deepseek_status():
    """Get DeepSeek brain status and performance stats."""
    brain = _get_deepseek_brain()
    if brain is None:
        return JSONResponse({'connected': False, 'error': 'Brain not initialized'})
    return JSONResponse(brain.get_stats())


@router.post('/api/deepseek/configure')
async def deepseek_configure(request: FastAPIRequest):
    """Update DeepSeek configuration at runtime."""
    body = await request.json()
    brain = _get_deepseek_brain()
    if brain is None:
        return JSONResponse({'error': 'Brain not initialized'}, status_code=500)

    if 'apiBase' in body:
        brain.config.api_base = body['apiBase']
    if 'model' in body:
        brain.config.model = body['model']
    if 'temperature' in body:
        brain.config.temperature = float(body['temperature'])
    if 'maxTokens' in body:
        brain.config.max_tokens = int(body['maxTokens'])
    if 'timeout' in body:
        brain.config.request_timeout = float(body['timeout'])
    if 'cacheEnabled' in body:
        brain.config.cache_enabled = bool(body['cacheEnabled'])
    if 'logDecisions' in body:
        brain.config.log_decisions = bool(body['logDecisions'])
    if 'fallbackOnTimeout' in body:
        brain.config.fallback_on_timeout = bool(body['fallbackOnTimeout'])

    connected = brain.check_connection()
    return JSONResponse({
        'connected': connected,
        'config': {
            'apiBase': brain.config.api_base,
            'model': brain.config.model,
            'temperature': brain.config.temperature,
            'maxTokens': brain.config.max_tokens,
            'timeout': brain.config.request_timeout,
            'cacheEnabled': brain.config.cache_enabled,
            'logDecisions': brain.config.log_decisions,
            'fallbackOnTimeout': brain.config.fallback_on_timeout,
        },
    })


@router.get('/api/deepseek/logs')
async def deepseek_logs():
    """Get decision log stats and flush pending entries."""
    brain = _get_deepseek_brain()
    if brain is None:
        return JSONResponse({'error': 'Brain not initialized'}, status_code=500)

    pending = len(brain._decision_log)
    flushed_path = None
    if pending > 0:
        try:
            flushed_path = brain.flush_log()
        except Exception as e:
            return JSONResponse({'error': f'Failed to flush: {e}'},
                                status_code=500)

    import glob as _glob
    log_dir = brain.config.log_dir
    log_files = []
    if log_dir and os.path.isdir(log_dir):
        for f in sorted(_glob.glob(os.path.join(log_dir, 'decisions_*.jsonl'))):
            stat = os.stat(f)
            log_files.append({
                'filename': os.path.basename(f),
                'size_bytes': stat.st_size,
                'modified': stat.st_mtime,
            })

    return JSONResponse({
        'flushed': pending,
        'flushedPath': flushed_path,
        'logFiles': log_files[-20:],
    })
  

@router.get("/api/validator/status")
async def validator_status():
    """Get DeepSeek-R1-14B validator brain status."""
    v = _get_validator_brain()
    if v is None:
        return JSONResponse({"enabled": False,
                             "reason": "VALIDATOR_ENABLED is not true"})
    return JSONResponse({"enabled": True, **v.get_stats()})


@router.post("/api/validator/configure")
async def validator_configure(request: FastAPIRequest):
    """Update validator configuration at runtime."""
    body = await request.json()
    v = _get_validator_brain()
    if v is None:
        return JSONResponse({"error": "Validator not enabled"}, status_code=400)
    if "model" in body:
        v.config.model = body["model"]
    if "timeout" in body:
        v.config.request_timeout = float(body["timeout"])
    if "enabled" in body:
        v.config.enabled = bool(body["enabled"])
    return JSONResponse(v.get_stats())
