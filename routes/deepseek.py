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
import os
import threading as _threading
import uuid as _uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi import Request as FastAPIRequest
from fastapi.responses import JSONResponse

from routes.shared import (
    CFG, log_sim,
    _get_db_conn,
    _ml_logging_enabled,
)

router = APIRouter(tags=["deepseek"])


# In-memory store for simulation runs
_sim_runs = {}  # sim_id -> { status, result, error }
_sim_lock = _threading.Lock()


def _run_sim_thread_v2(sim_id: str, card_data: list[dict], num_games: int, deck_name: str, record_logs: bool):
    """Background thread for simulations with full card data from the DB."""
    try:
        import sys, os
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        from commander_ai_lab.sim.models import Card
        from commander_ai_lab.sim.engine import GameEngine
        from commander_ai_lab.sim.rules import enrich_card
        from commander_ai_lab.lab.experiments import _generate_training_deck

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        # Build deck with real card data from DB
        deck_a = []
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
                        import json as _json
                        kw = _json.loads(kw)
                    except Exception:
                        kw = []
                if isinstance(kw, list):
                    c.keywords = kw
            # Enrich fills in flags like is_removal, is_ramp, is_board_wipe
            enrich_card(c)
            deck_a.append(c)

        deck_b = _generate_training_deck()

        engine = GameEngine(max_turns=25, record_log=record_logs)
        import time
        start = time.time()

        wins = 0
        losses = 0
        total_turns = 0
        total_damage_dealt = 0
        total_damage_received = 0
        total_spells_cast = 0
        total_creatures_played = 0
        total_removal_used = 0
        total_ramp_played = 0
        total_cards_drawn = 0
        total_max_board = 0
        game_results = []

        for i in range(num_games):
            result = engine.run(deck_a, deck_b, name_a=deck_name, name_b="Training Deck")

            game_data = result.to_dict()
            game_data['gameNumber'] = i + 1
            game_results.append(game_data)

            if result.winner == 0:
                wins += 1
            else:
                losses += 1

            total_turns += result.turns
            if result.player_a_stats:
                total_damage_dealt += result.player_a_stats.damage_dealt
                total_damage_received += result.player_a_stats.damage_received
                total_spells_cast += result.player_a_stats.spells_cast
                total_creatures_played += result.player_a_stats.creatures_played
                total_removal_used += result.player_a_stats.removal_used
                total_ramp_played += result.player_a_stats.ramp_played
                total_cards_drawn += result.player_a_stats.cards_drawn
                total_max_board += result.player_a_stats.max_board_size

            with _sim_lock:
                _sim_runs[sim_id]['completed'] = i + 1

        elapsed = time.time() - start
        n = num_games

        summary = {
            'deckName': deck_name,
            'opponentName': 'Training Deck',
            'totalGames': n,
            'wins': wins,
            'losses': losses,
            'winRate': round(wins / n * 100, 1) if n > 0 else 0.0,
            'avgTurns': round(total_turns / n, 1) if n > 0 else 0.0,
            'avgDamageDealt': round(total_damage_dealt / n, 1) if n > 0 else 0.0,
            'avgDamageReceived': round(total_damage_received / n, 1) if n > 0 else 0.0,
            'avgSpellsCast': round(total_spells_cast / n, 1) if n > 0 else 0.0,
            'avgCreaturesPlayed': round(total_creatures_played / n, 1) if n > 0 else 0.0,
            'avgRemovalUsed': round(total_removal_used / n, 1) if n > 0 else 0.0,
            'avgRampPlayed': round(total_ramp_played / n, 1) if n > 0 else 0.0,
            'avgCardsDrawn': round(total_cards_drawn / n, 1) if n > 0 else 0.0,
            'avgMaxBoardSize': round(total_max_board / n, 1) if n > 0 else 0.0,
            'elapsedSeconds': round(elapsed, 3),
        }

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'complete'
            _sim_runs[sim_id]['result'] = {
                'summary': summary,
                'games': game_results,
            }
    except Exception as e:
        import traceback
        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'error'
            _sim_runs[sim_id]['error'] = str(e)
        traceback.print_exc()


def _run_sim_thread(sim_id: str, decklist: list, num_games: int, deck_name: str, record_logs: bool):
    """Background thread for running Monte Carlo simulations."""
    try:
        import sys, os
        # Add src/ to path if needed for the simulator package
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        from commander_ai_lab.sim.models import Card
        from commander_ai_lab.sim.engine import GameEngine
        from commander_ai_lab.sim.rules import enrich_card, parse_decklist
        from commander_ai_lab.lab.experiments import build_deck, _generate_training_deck

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        deck_a = build_deck(decklist)
        deck_b = _generate_training_deck()

        engine = GameEngine(max_turns=25, record_log=record_logs)
        import time
        start = time.time()

        wins = 0
        losses = 0
        total_turns = 0
        total_damage_dealt = 0
        total_damage_received = 0
        total_spells_cast = 0
        total_creatures_played = 0
        total_removal_used = 0
        total_ramp_played = 0
        total_cards_drawn = 0
        total_max_board = 0
        game_results = []

        for i in range(num_games):
            result = engine.run(deck_a, deck_b, name_a=deck_name, name_b="Training Deck")

            game_data = result.to_dict()
            game_data['gameNumber'] = i + 1
            game_results.append(game_data)

            if result.winner == 0:
                wins += 1
            else:
                losses += 1

            total_turns += result.turns
            if result.player_a_stats:
                total_damage_dealt += result.player_a_stats.damage_dealt
                total_damage_received += result.player_a_stats.damage_received
                total_spells_cast += result.player_a_stats.spells_cast
                total_creatures_played += result.player_a_stats.creatures_played
                total_removal_used += result.player_a_stats.removal_used
                total_ramp_played += result.player_a_stats.ramp_played
                total_cards_drawn += result.player_a_stats.cards_drawn
                total_max_board += result.player_a_stats.max_board_size

            # Update progress
            with _sim_lock:
                _sim_runs[sim_id]['completed'] = i + 1

        elapsed = time.time() - start
        n = num_games

        summary = {
            'deckName': deck_name,
            'opponentName': 'Training Deck',
            'totalGames': n,
            'wins': wins,
            'losses': losses,
            'winRate': round(wins / n * 100, 1) if n > 0 else 0.0,
            'avgTurns': round(total_turns / n, 1) if n > 0 else 0.0,
            'avgDamageDealt': round(total_damage_dealt / n, 1) if n > 0 else 0.0,
            'avgDamageReceived': round(total_damage_received / n, 1) if n > 0 else 0.0,
            'avgSpellsCast': round(total_spells_cast / n, 1) if n > 0 else 0.0,
            'avgCreaturesPlayed': round(total_creatures_played / n, 1) if n > 0 else 0.0,
            'avgRemovalUsed': round(total_removal_used / n, 1) if n > 0 else 0.0,
            'avgRampPlayed': round(total_ramp_played / n, 1) if n > 0 else 0.0,
            'avgCardsDrawn': round(total_cards_drawn / n, 1) if n > 0 else 0.0,
            'avgMaxBoardSize': round(total_max_board / n, 1) if n > 0 else 0.0,
            'elapsedSeconds': round(elapsed, 3),
        }

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'complete'
            _sim_runs[sim_id]['result'] = {
                'summary': summary,
                'games': game_results,
            }
    except Exception as e:
        import traceback
        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'error'
            _sim_runs[sim_id]['error'] = str(e)
        traceback.print_exc()


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

    sim_id = str(_uuid.uuid4())[:8]
    with _sim_lock:
        _sim_runs[sim_id] = {
            'status': 'queued',
            'completed': 0,
            'total': num_games,
            'deckName': deck_name,
            'result': None,
            'error': None,
        }

    t = _threading.Thread(target=_run_sim_thread, args=(sim_id, decklist, num_games, deck_name, record_logs), daemon=True)
    t.start()

    return JSONResponse({'simId': sim_id, 'status': 'queued', 'total': num_games})


@router.get('/api/sim/status')
async def sim_status(simId: str):
    """Poll simulation progress."""
    with _sim_lock:
        run = _sim_runs.get(simId)
    if not run:
        return JSONResponse({'error': 'sim not found'}, status_code=404)
    return JSONResponse({
        'simId': simId,
        'status': run['status'],
        'completed': run['completed'],
        'total': run['total'],
        'deckName': run.get('deckName', ''),
        'error': run.get('error'),
    })


@router.get('/api/sim/result')
async def sim_result(simId: str):
    """Get completed simulation results."""
    with _sim_lock:
        run = _sim_runs.get(simId)
    if not run:
        return JSONResponse({'error': 'sim not found'}, status_code=404)
    if run['status'] != 'complete':
        return JSONResponse({'error': 'sim not complete', 'status': run['status']}, status_code=400)
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

    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute('SELECT name FROM decks WHERE id = ?', (deck_id,))
    row = cur.fetchone()
    if not row:
        return JSONResponse({'error': 'deck not found'}, status_code=404)
    deck_name = row[0]

    # Pull full card data from collection join so the sim engine has real types/stats
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
                'name': r[0],
                'type_line': r[2] or '',
                'cmc': r[3] or 0,
                'power': r[4] or '',
                'toughness': r[5] or '',
                'oracle_text': r[6] or '',
                'keywords': r[7] or '',
                'mana_cost': r[8] or '',
            })
    if not card_data:
        return JSONResponse({'error': 'deck has no cards'}, status_code=400)

    sim_id = str(_uuid.uuid4())[:8]
    with _sim_lock:
        _sim_runs[sim_id] = {
            'status': 'queued',
            'completed': 0,
            'total': num_games,
            'deckName': deck_name,
            'result': None,
            'error': None,
        }

    t = _threading.Thread(target=_run_sim_thread_v2, args=(sim_id, card_data, num_games, deck_name, record_logs), daemon=True)
    t.start()

    return JSONResponse({'simId': sim_id, 'status': 'queued', 'total': num_games, 'deckName': deck_name})


# ══════════════════════════════════════════════════════════════
# DeepSeek AI Opponent Brain
# ══════════════════════════════════════════════════════════════

# Global DeepSeek brain instance (lazy-initialized)
_deepseek_brain = None
_deepseek_lock = _threading.Lock()

def _get_deepseek_brain():
    """Get or create the global DeepSeek brain instance."""
    global _deepseek_brain
    if _deepseek_brain is None:
        with _deepseek_lock:
            if _deepseek_brain is None:
                try:
                    import sys as _sys2, os as _os2
                    src_dir = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), 'src')
                    if src_dir not in _sys2.path:
                        _sys2.path.insert(0, src_dir)
                    from commander_ai_lab.sim.deepseek_brain import DeepSeekBrain, DeepSeekConfig
                    cfg = DeepSeekConfig()
                    # Allow env var overrides
                    if _os2.environ.get('DEEPSEEK_API_BASE'):
                        cfg.api_base = _os2.environ['DEEPSEEK_API_BASE']
                    if _os2.environ.get('DEEPSEEK_MODEL'):
                        cfg.model = _os2.environ['DEEPSEEK_MODEL']
                    cfg.log_dir = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)), 'logs', 'decisions')
                    _deepseek_brain = DeepSeekBrain(cfg)
                except Exception as e:
                    log_sim.error(f'Failed to initialize brain: {e}')
                    return None
    return _deepseek_brain


@router.post('/api/deepseek/connect')
async def deepseek_connect(request: FastAPIRequest):
    """Test connection to the DeepSeek LLM endpoint and auto-detect model."""
    body = await request.json() if await request.body() else {}
    api_base = body.get('apiBase', None)
    model = body.get('model', None)

    brain = _get_deepseek_brain()
    if brain is None:
        return JSONResponse({'error': 'DeepSeek brain failed to initialize'}, status_code=500)

    # Allow runtime reconfiguration
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

    # Re-test connection with new settings
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
            return JSONResponse({'error': f'Failed to flush: {e}'}, status_code=500)

    # List existing log files
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
        'logFiles': log_files[-20:],  # last 20
    })


def _run_sim_thread_deepseek(sim_id: str, card_data: list[dict], num_games: int, deck_name: str, record_logs: bool):
    """Background thread for simulations using DeepSeek AI opponent."""
    try:
        import sys, os
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        from commander_ai_lab.sim.models import Card
        from commander_ai_lab.sim.deepseek_engine import DeepSeekGameEngine
        from commander_ai_lab.sim.rules import enrich_card
        from commander_ai_lab.lab.experiments import _generate_training_deck

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'running'

        # Build player's deck with real card data
        deck_a = []
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
                        import json as _json
                        kw = _json.loads(kw)
                    except Exception:
                        kw = []
                if isinstance(kw, list):
                    c.keywords = kw
            enrich_card(c)
            deck_a.append(c)

        deck_b = _generate_training_deck()

        # Get DeepSeek brain
        brain = _get_deepseek_brain()
        if brain and not brain._connected:
            brain.check_connection()

        engine = DeepSeekGameEngine(
            brain=brain,
            ai_player_index=1,  # Training deck is player B (index 1)
            max_turns=25,
            record_log=record_logs,
        )

        import time
        start = time.time()

        wins = 0
        losses = 0
        total_turns = 0
        total_damage_dealt = 0
        total_damage_received = 0
        total_spells_cast = 0
        total_creatures_played = 0
        total_removal_used = 0
        total_ramp_played = 0
        total_cards_drawn = 0
        total_max_board = 0
        game_results = []

        for i in range(num_games):
            game_id = f'ds-sim-{sim_id[:8]}-g{i+1}'
            result = engine.run(deck_a, deck_b, name_a=deck_name, name_b='DeepSeek AI',
                               game_id=game_id, archetype='midrange')

            game_data = result.to_dict()
            game_data['gameNumber'] = i + 1
            game_results.append(game_data)

            if result.winner == 0:
                wins += 1
            else:
                losses += 1

            total_turns += result.turns
            if result.player_a_stats:
                total_damage_dealt += result.player_a_stats.damage_dealt
                total_damage_received += result.player_a_stats.damage_received
                total_spells_cast += result.player_a_stats.spells_cast
                total_creatures_played += result.player_a_stats.creatures_played
                total_removal_used += result.player_a_stats.removal_used
                total_ramp_played += result.player_a_stats.ramp_played
                total_cards_drawn += result.player_a_stats.cards_drawn
                total_max_board += result.player_a_stats.max_board_size

            with _sim_lock:
                _sim_runs[sim_id]['completed'] = i + 1

        elapsed = time.time() - start
        n = num_games

        # Write ML decision JSONL for training pipeline
        ml_decisions = engine.flush_ml_decisions()
        if ml_decisions:
            ml_jsonl_path = os.path.join('results', f'ml-decisions-sim-{sim_id[:8]}.jsonl')
            os.makedirs('results', exist_ok=True)
            with open(ml_jsonl_path, 'w', encoding='utf-8') as mf:
                import json as _mljson
                for dec in ml_decisions:
                    mf.write(_mljson.dumps(dec) + '\n')

        # Get DeepSeek stats for the summary
        ds_stats = brain.get_stats() if brain else {}

        summary = {
            'deckName': deck_name,
            'opponentName': 'DeepSeek AI',
            'opponentType': 'deepseek',
            'totalGames': n,
            'wins': wins,
            'losses': losses,
            'winRate': round(wins / n * 100, 1) if n > 0 else 0.0,
            'avgTurns': round(total_turns / n, 1) if n > 0 else 0.0,
            'avgDamageDealt': round(total_damage_dealt / n, 1) if n > 0 else 0.0,
            'avgDamageReceived': round(total_damage_received / n, 1) if n > 0 else 0.0,
            'avgSpellsCast': round(total_spells_cast / n, 1) if n > 0 else 0.0,
            'avgCreaturesPlayed': round(total_creatures_played / n, 1) if n > 0 else 0.0,
            'avgRemovalUsed': round(total_removal_used / n, 1) if n > 0 else 0.0,
            'avgRampPlayed': round(total_ramp_played / n, 1) if n > 0 else 0.0,
            'avgCardsDrawn': round(total_cards_drawn / n, 1) if n > 0 else 0.0,
            'avgMaxBoardSize': round(total_max_board / n, 1) if n > 0 else 0.0,
            'elapsedSeconds': round(elapsed, 3),
            'deepseekStats': ds_stats,
        }

        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'complete'
            _sim_runs[sim_id]['result'] = {
                'summary': summary,
                'games': game_results,
            }
    except Exception as e:
        import traceback
        with _sim_lock:
            _sim_runs[sim_id]['status'] = 'error'
            _sim_runs[sim_id]['error'] = str(e)
        traceback.print_exc()


@router.post('/api/sim/run-deepseek')
async def sim_run_deepseek(request: FastAPIRequest):
    """Start simulation using DeepSeek AI as the opponent brain."""
    body = await request.json()
    deck_id = body.get('deckId')
    num_games = body.get('numGames', 5)  # Default 5 (LLM is slower)
    record_logs = body.get('recordLogs', True)

    if not deck_id:
        return JSONResponse({'error': 'deckId required'}, status_code=400)
    if num_games < 1 or num_games > 50:
        return JSONResponse({'error': 'numGames must be 1-50 for DeepSeek mode'}, status_code=400)

    conn = _get_db_conn()
    cur = conn.cursor()
    cur.execute('SELECT name FROM decks WHERE id = ?', (deck_id,))
    row = cur.fetchone()
    if not row:
        return JSONResponse({'error': 'deck not found'}, status_code=404)
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
                'name': r[0],
                'type_line': r[2] or '',
                'cmc': r[3] or 0,
                'power': r[4] or '',
                'toughness': r[5] or '',
                'oracle_text': r[6] or '',
                'keywords': r[7] or '',
                'mana_cost': r[8] or '',
            })
    if not card_data:
        return JSONResponse({'error': 'deck has no cards'}, status_code=400)

    sim_id = str(_uuid.uuid4())[:8]
    with _sim_lock:
        _sim_runs[sim_id] = {
            'status': 'queued',
            'completed': 0,
            'total': num_games,
            'deckName': deck_name,
            'result': None,
            'error': None,
        }

    t = _threading.Thread(
        target=_run_sim_thread_deepseek,
        args=(sim_id, card_data, num_games, deck_name, record_logs),
        daemon=True,
    )
    t.start()

    return JSONResponse({
        'simId': sim_id,
        'status': 'queued',
        'total': num_games,
        'deckName': deck_name,
        'opponentType': 'deepseek',
    })


