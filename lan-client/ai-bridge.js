// ai-bridge.js — Commander-AI-Lab Backend Bridge
// Manages REST + WebSocket connectivity to the Commander-AI-Lab backend.

'use strict';

const AI_BRIDGE_VERSION = '1.0.0';

// ============================================================
// CONFIGURATION
// ============================================================

const AI_BRIDGE_CONFIG = {
  // Backend URL — defaults to localhost:8080, configurable via settings
  backendUrl: 'http://localhost:8080',
  wsUrl: 'ws://localhost:8080',

  // Timeouts (ms)
  healthCheckTimeout: 3000,
  decisionTimeout: 5000,
  reconnectInterval: 10000,

  // Retry policy
  maxRetries: 2,
  retryDelayMs: 500,

  // Feature flags
  enableWebSocket: true,
  enableStateSync: true,
  fallbackToLocalAi: true,

  // Logging
  verbose: false,
};

// ============================================================
// BACKEND CONNECTOR
// ============================================================

class BackendConnector {
  constructor(config = {}) {
    this.config = { ...AI_BRIDGE_CONFIG, ...config };
    this._connected = false;
    this._modelLoaded = false;
    this._ws = null;
    this._gameId = null;
    this._reconnectTimer = null;
    this._healthCheckTimer = null;
    this._lastHealthCheck = 0;
    this._eventListeners = {};
  }

  // ── Connection Management ─────────────────────────────────

  /**
   * Test connectivity to the backend. Returns true if the backend
   * is reachable and the health endpoint responds.
   */
  async checkHealth() {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(
        () => controller.abort(),
        this.config.healthCheckTimeout
      );

      const resp = await fetch(`${this.config.backendUrl}/api/health`, {
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (resp.ok) {
        const data = await resp.json();
        this._connected = data.status === 'ok';
        this._lastHealthCheck = Date.now();
        return this._connected;
      }
      this._connected = false;
      return false;
    } catch (e) {
      this._connected = false;
      if (this.config.verbose) {
        console.warn('[AI Bridge] Health check failed:', e.message);
      }
      return false;
    }
  }

  /**
   * Check if the ML policy model is loaded and ready for inference.
   */
  async checkModelStatus() {
    if (!this._connected) return false;
    try {
      const resp = await fetch(
        `${this.config.backendUrl}/api/policy/health`
      );
      if (resp.ok) {
        const data = await resp.json();
        this._modelLoaded = data.ready === true;
        return this._modelLoaded;
      }
      return false;
    } catch (e) {
      this._modelLoaded = false;
      return false;
    }
  }

  /**
   * Full initialization: health check + model status.
   * Returns { connected, modelLoaded }.
   */
  async initialize() {
    const connected = await this.checkHealth();
    let modelLoaded = false;
    if (connected) {
      modelLoaded = await this.checkModelStatus();
    }
    this._emit('status', { connected, modelLoaded });
    return { connected, modelLoaded };
  }

  // ── REST API Calls ─────────────────────────────────────────

  /**
   * POST to any backend endpoint with JSON body.
   * Includes retry logic and timeout handling.
   */
  async _post(path, body, timeoutMs) {
    const url = `${this.config.backendUrl}${path}`;
    let lastError = null;

    for (let attempt = 0; attempt <= this.config.maxRetries; attempt++) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(
          () => controller.abort(),
          timeoutMs || this.config.decisionTimeout
        );

        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        clearTimeout(timeout);

        if (resp.ok) {
          return await resp.json();
        }
        lastError = new Error(`HTTP ${resp.status}: ${resp.statusText}`);
      } catch (e) {
        lastError = e;
        if (attempt < this.config.maxRetries) {
          await new Promise(r =>
            setTimeout(r, this.config.retryDelayMs * (attempt + 1))
          );
        }
      }
    }
    throw lastError;
  }

  /**
   * GET from any backend endpoint.
   */
  async _get(path, timeoutMs) {
    const url = `${this.config.backendUrl}${path}`;
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      timeoutMs || this.config.healthCheckTimeout
    );
    try {
      const resp = await fetch(url, { signal: controller.signal });
      clearTimeout(timeout);
      if (resp.ok) return await resp.json();
      throw new Error(`HTTP ${resp.status}`);
    } catch (e) {
      clearTimeout(timeout);
      throw e;
    }
  }

  // ── WebSocket Management ──────────────────────────────────

  /**
   * Open a WebSocket connection for a game session.
   * Receives state deltas, decision events, and game-over signals.
   */
  connectWebSocket(gameId, clientId) {
    if (!this.config.enableWebSocket) return;
    if (this._ws) this.disconnectWebSocket();

    this._gameId = gameId;
    const cid = clientId || `lan-${Date.now().toString(36)}`;
    const url = `${this.config.wsUrl}/ws/game/${gameId}?client_id=${cid}`;

    try {
      this._ws = new WebSocket(url);

      this._ws.onopen = () => {
        if (this.config.verbose) {
          console.log('[AI Bridge] WebSocket connected:', gameId);
        }
        this._emit('ws:connected', { gameId });
      };

      this._ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          this._handleWsMessage(msg);
        } catch (e) {
          console.warn('[AI Bridge] WS message parse error:', e);
        }
      };

      this._ws.onclose = (event) => {
        if (this.config.verbose) {
          console.log('[AI Bridge] WebSocket closed:', event.code);
        }
        this._ws = null;
        this._emit('ws:disconnected', { gameId, code: event.code });

        // Auto-reconnect if game is still active
        if (this._gameId && this.config.enableWebSocket) {
          this._reconnectTimer = setTimeout(() => {
            this.connectWebSocket(gameId, cid);
          }, this.config.reconnectInterval);
        }
      };

      this._ws.onerror = (error) => {
        console.warn('[AI Bridge] WebSocket error:', error);
        this._emit('ws:error', { error });
      };
    } catch (e) {
      console.warn('[AI Bridge] WebSocket connection failed:', e);
    }
  }

  disconnectWebSocket() {
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._ws) {
      this._ws.onclose = null; // prevent auto-reconnect
      this._ws.close();
      this._ws = null;
    }
    this._gameId = null;
  }

  _handleWsMessage(msg) {
    switch (msg.type) {
      case 'snapshot':
        this._emit('state:snapshot', msg);
        break;
      case 'delta':
        this._emit('state:delta', msg);
        break;
      case 'decision':
        this._emit('ai:decision', msg);
        break;
      case 'game_over':
        this._emit('game:over', msg);
        break;
      case 'pong':
        break;
      case 'heartbeat':
        break;
      default:
        if (this.config.verbose) {
          console.log('[AI Bridge] Unknown WS message type:', msg.type);
        }
    }
  }

  // ── Event System ──────────────────────────────────────────

  on(event, callback) {
    if (!this._eventListeners[event]) {
      this._eventListeners[event] = [];
    }
    this._eventListeners[event].push(callback);
    return () => this.off(event, callback);
  }

  off(event, callback) {
    const listeners = this._eventListeners[event];
    if (listeners) {
      this._eventListeners[event] = listeners.filter(cb => cb !== callback);
    }
  }

  _emit(event, data) {
    const listeners = this._eventListeners[event] || [];
    listeners.forEach(cb => {
      try {
        cb(data);
      } catch (e) {
        console.error(`[AI Bridge] Event handler error (${event}):`, e);
      }
    });
  }

  // ── Status ────────────────────────────────────────────────

  get connected() { return this._connected; }
  get modelLoaded() { return this._modelLoaded; }
  get wsConnected() { return this._ws && this._ws.readyState === WebSocket.OPEN; }
  get gameId() { return this._gameId; }

  getStatus() {
    return {
      connected: this._connected,
      modelLoaded: this._modelLoaded,
      wsConnected: this.wsConnected,
      gameId: this._gameId,
      lastHealthCheck: this._lastHealthCheck,
    };
  }

  destroy() {
    this.disconnectWebSocket();
    if (this._healthCheckTimer) clearInterval(this._healthCheckTimer);
    this._eventListeners = {};
  }
}

// ============================================================
// GAME STATE BRIDGE
// ============================================================

class GameStateBridge {
  constructor(connector) {
    this.connector = connector;
    this._sessionGameId = null;
    this._stateTracker = null;
  }

  // ── Session Lifecycle ──────────────────────────────────────

  /**
   * Create a game session on the backend when a new game starts.
   * Maps the LAN app's player setup to SeatConfig objects.
   */
  async initSession(gameState) {
    if (!this.connector.connected) return null;

    const seats = gameState.players.map((p, i) => ({
      seat_index: i,
      seat_type: p.isAI
        ? this._mapAiProfile(gameState.aiDifficulty)
        : 'Human',
      deck_name: p.commanderCardName || '',
      player_name: p.name,
    }));

    try {
      const resp = await this.connector._post('/api/game/start', {
        seats,
      });
      this._sessionGameId = resp.game_id;

      // Connect WebSocket for this session
      this.connector.connectWebSocket(resp.game_id);

      if (AI_BRIDGE_CONFIG.verbose) {
        console.log('[GameStateBridge] Session created:', resp.game_id);
      }
      return resp;
    } catch (e) {
      console.warn('[GameStateBridge] Failed to create session:', e);
      return null;
    }
  }

  /**
   * Map LAN app difficulty to backend AI profile.
   */
  _mapAiProfile(difficulty) {
    const map = {
      easy: 'AI',
      normal: 'AI Aggro',
      hard: 'AI Control',
    };
    return map[difficulty] || 'AI';
  }

  // ── Game State Serialization ──────────────────────────────

  /**
   * Convert the JS gameState to a DecisionSnapshot-compatible
   * object for the /api/policy/decide endpoint.
   */
  serializeGameState(gameState, playerIdx) {
    const players = gameState.players.map((p, i) => {
      // Count creatures on battlefield
      const bfCards = this._getBattlefieldCards(p, gameState);
      const creatures = bfCards.filter(c =>
        c.typeLine && c.typeLine.toLowerCase().includes('creature')
      );
      const totalPower = creatures.reduce((sum, c) => {
        const pow = parseInt(c.power) || 0;
        return sum + pow;
      }, 0);

      // Count lands on battlefield
      const lands = bfCards.filter(c =>
        c.typeLine && c.typeLine.toLowerCase().includes('land')
      );

      // Build mana availability from untapped lands
      const untappedLands = lands.filter(c => !c.tapped);
      const manaAvailable = untappedLands.length +
        (p.manaPool ? getManaPoolTotal(p.manaPool) : 0);

      // Commander damage received (sum from all opponents)
      const cmdrDmg = {};
      if (p.commanderDamage) {
        for (const [oppId, dmg] of Object.entries(p.commanderDamage)) {
          cmdrDmg[String(oppId)] = dmg;
        }
      }

      return {
        seat: i,
        name: p.name,
        life: p.life,
        poison: p.poison || 0,
        cmdr_dmg: cmdrDmg,
        cmdr_tax: (p.commanderCastCount || 0) * 2,
        commanderTax: (p.commanderCastCount || 0) * 2,
        mana_available: manaAvailable,
        manaAvailable: manaAvailable,

        // Zone contents — card names
        hand: p.zones.hand.map(c => c.name || 'Unknown'),
        hand_count: p.zones.hand.length,
        battlefield: bfCards.map(c => ({
          name: c.name || 'Unknown',
          type: c.typeLine || '',
          power: c.power || '0',
          toughness: c.toughness || '0',
          tapped: !!c.tapped,
        })),
        graveyard: p.zones.graveyard.map(c => c.name || 'Unknown'),
        exile: p.zones.exile.map(c => c.name || 'Unknown'),
        command_zone: p.zones.command.map(c => c.name || 'Unknown'),
        library_count: p.zones.library.length,

        // Pre-computed board stats
        creaturesOnField: creatures.length,
        totalPowerOnBoard: totalPower,
        landCount: lands.length,
        artifactsOnField: bfCards.filter(c =>
          c.typeLine && c.typeLine.toLowerCase().includes('artifact')
        ).length,
        enchantmentsOnField: bfCards.filter(c =>
          c.typeLine && c.typeLine.toLowerCase().includes('enchantment')
        ).length,
      };
    });

    // Map current phase to backend format
    const phaseId = PHASES[gameState.currentPhaseIndex]?.id || 'main1';
    const phaseMap = {
      beginning: 'main_1',
      main1: 'main_1',
      combat: 'combat',
      main2: 'main_2',
      end: 'end',
    };

    return {
      game_id: this._sessionGameId || '',
      turn: gameState.turnCounter || 1,
      phase: phaseMap[phaseId] || 'main_1',
      active_player: playerIdx,
      players: players,
      stack: [],
      legal_actions: [],
      playstyle: this._inferPlaystyle(gameState, playerIdx),
      greedy: false,
      temperature: 1.0,
      commander: gameState.players[playerIdx]?.commanderCardName || '',
    };
  }

  /**
   * Get all battlefield cards for a player.
   */
  _getBattlefieldCards(player, gameState) {
    if (!gameState || !gameState.battlefield) return [];
    return (gameState.battlefield || []).filter(
      c => c.controller === player.id || c.owner === player.id
    );
  }

  /**
   * Infer a playstyle hint for the AI based on the deck composition.
   */
  _inferPlaystyle(gameState, playerIdx) {
    const player = gameState.players[playerIdx];
    if (!player) return 'midrange';

    const cmdr = player.commanderCardName || '';
    if (!cmdr) return 'midrange';

    const allCards = [
      ...player.zones.hand,
      ...player.zones.graveyard,
      ...player.zones.library,
    ];
    if (allCards.length === 0) return 'midrange';

    const creatures = allCards.filter(c =>
      c.typeLine && c.typeLine.toLowerCase().includes('creature')
    );
    const creatureRatio = creatures.length / allCards.length;

    if (creatureRatio > 0.35) return 'aggro';
    if (creatureRatio < 0.20) return 'control';
    return 'midrange';
  }

  // ── AI Decision Request ───────────────────────────────────

  /**
   * Request an AI decision from the backend policy server.
   * Returns the macro-action prediction or null if unavailable.
   */
  async requestAiDecision(gameState, playerIdx) {
    if (!this.connector.connected || !this.connector.modelLoaded) {
      return null;
    }

    try {
      const snapshot = this.serializeGameState(gameState, playerIdx);
      const result = await this.connector._post(
        '/api/policy/decide',
        snapshot,
        AI_BRIDGE_CONFIG.decisionTimeout
      );

      if (result.error) {
        console.warn('[GameStateBridge] Decision error:', result.error);
        return null;
      }

      return result;
    } catch (e) {
      console.warn('[GameStateBridge] Decision request failed:', e);
      return null;
    }
  }

  // ── State Sync ────────────────────────────────────────────

  /**
   * Push current game state to the backend WebSocket layer.
   */
  async pushState(gameState) {
    if (!this._sessionGameId || !this.connector.connected) return;
    if (!AI_BRIDGE_CONFIG.enableStateSync) return;

    try {
      const snapshot = this.serializeGameState(
        gameState,
        gameState.currentPlayerIndex
      );
      await this.connector._post(
        `/api/ws/game/${this._sessionGameId}/push`,
        snapshot
      );
    } catch (e) {
      // Non-critical — log but don't fail
      if (AI_BRIDGE_CONFIG.verbose) {
        console.warn('[GameStateBridge] State push failed:', e);
      }
    }
  }

  /**
   * Push an AI decision event to connected WebSocket clients.
   */
  async pushDecision(decision) {
    if (!this._sessionGameId || !this.connector.connected) return;

    try {
      await this.connector._post(
        `/api/ws/game/${this._sessionGameId}/decision`,
        {
          action: decision.action,
          action_index: decision.action_index,
          confidence: decision.confidence,
          probabilities: decision.probabilities || {},
          inference_ms: decision.inference_ms || 0,
        }
      );
    } catch (e) {
      // Non-critical
    }
  }

  // ── Cleanup ───────────────────────────────────────────────

  async endSession() {
    if (this._sessionGameId && this.connector.connected) {
      try {
        await this.connector._post(
          `/api/ws/game/${this._sessionGameId}/end`,
          {
            winner_seat: -1,
            reason: 'session_ended',
            turns_played: 0,
          }
        );
      } catch (e) {
        // Non-critical
      }
    }
    this.connector.disconnectWebSocket();
    this._sessionGameId = null;
  }
}

// ============================================================
// MACRO ACTION MAPPER
// ============================================================

class MacroActionMapper {
  /**
   * Execute a macro-action by calling the appropriate engine.js functions.
   *
   * @param {string} action - One of the 8 MacroAction values
   * @param {number} playerIdx - Index of the AI player
   * @param {object} gameState - Current game state
   * @param {object} decision - Full decision response from backend
   * @returns {boolean} Whether the action was successfully executed
   */
  static execute(action, playerIdx, gameState, decision) {
    const player = gameState.players[playerIdx];
    if (!player) return false;

    const confidence = decision?.confidence || 0;

    switch (action) {
      case 'cast_creature':
        return MacroActionMapper._castCreature(playerIdx, player, gameState, confidence);

      case 'cast_removal':
        return MacroActionMapper._castRemoval(playerIdx, player, gameState);

      case 'cast_draw':
        return MacroActionMapper._castDraw(playerIdx, player, gameState);

      case 'cast_ramp':
        return MacroActionMapper._castRamp(playerIdx, player, gameState);

      case 'cast_commander':
        return MacroActionMapper._castCommander(playerIdx, player, gameState);

      case 'attack_opponent':
        return MacroActionMapper._attackOpponent(playerIdx, player, gameState);

      case 'hold_mana':
        MacroActionMapper._log(playerIdx, player,
          'holding mana open', confidence);
        return true;

      case 'pass':
        MacroActionMapper._log(playerIdx, player,
          'passing', confidence);
        return true;

      default:
        console.warn('[MacroActionMapper] Unknown action:', action);
        return false;
    }
  }

  // ── Cast Creature ─────────────────────────────────────────

  static _castCreature(playerIdx, player, gameState, confidence) {
    const hand = player.zones.hand;
    const creatures = hand.filter(c =>
      c.typeLine && c.typeLine.toLowerCase().includes('creature')
    );

    if (creatures.length === 0) {
      const castable = hand.filter(c => !MacroActionMapper._isLand(c));
      if (castable.length === 0) return false;
      castable.sort((a, b) => (MacroActionMapper._cmc(b) - MacroActionMapper._cmc(a)));
      for (const card of castable) {
        if (MacroActionMapper._canAfford(playerIdx, card)) {
          const idx = hand.indexOf(card);
          if (idx !== -1) {
            if (!card.imageUrl) card.imageUrl = generateAiCardSVG(card);
            playCardFromHand(playerIdx, idx);
            MacroActionMapper._log(playerIdx, player,
              `cast <strong>${card.name}</strong> (creature slot)`, confidence);
            return true;
          }
        }
      }
      return false;
    }

    creatures.sort((a, b) => {
      const aScore = MacroActionMapper._creatureScore(a);
      const bScore = MacroActionMapper._creatureScore(b);
      return bScore - aScore;
    });

    for (const card of creatures) {
      if (MacroActionMapper._canAfford(playerIdx, card)) {
        const idx = hand.indexOf(card);
        if (idx !== -1) {
          if (!card.imageUrl) card.imageUrl = generateAiCardSVG(card);
          playCardFromHand(playerIdx, idx);
          MacroActionMapper._log(playerIdx, player,
            `cast <strong>${card.name}</strong>`, confidence);
          return true;
        }
      }
    }
    return false;
  }

  // ── Cast Removal ──────────────────────────────────────────

  static _castRemoval(playerIdx, player, gameState) {
    const hand = player.zones.hand;
    const removal = hand.filter(c => c.isRemoval || c.isBoardWipe ||
      MacroActionMapper._looksLikeRemoval(c));

    if (removal.length === 0) return false;

    for (const card of removal) {
      if (MacroActionMapper._canAfford(playerIdx, card)) {
        const idx = hand.indexOf(card);
        if (idx !== -1) {
          if (!card.imageUrl) card.imageUrl = generateAiCardSVG(card);
          playCardFromHand(playerIdx, idx);
          MacroActionMapper._log(playerIdx, player,
            `cast removal <strong>${card.name}</strong>`);
          return true;
        }
      }
    }
    return false;
  }

  // ── Cast Draw ─────────────────────────────────────────────

  static _castDraw(playerIdx, player, gameState) {
    const hand = player.zones.hand;
    const drawSpells = hand.filter(c =>
      MacroActionMapper._looksLikeDraw(c)
    );

    if (drawSpells.length === 0) return false;

    drawSpells.sort((a, b) =>
      MacroActionMapper._cmc(a) - MacroActionMapper._cmc(b)
    );

    for (const card of drawSpells) {
      if (MacroActionMapper._canAfford(playerIdx, card)) {
        const idx = hand.indexOf(card);
        if (idx !== -1) {
          if (!card.imageUrl) card.imageUrl = generateAiCardSVG(card);
          playCardFromHand(playerIdx, idx);
          MacroActionMapper._log(playerIdx, player,
            `cast draw spell <strong>${card.name}</strong>`);
          return true;
        }
      }
    }
    return false;
  }

  // ── Cast Ramp ─────────────────────────────────────────────

  static _castRamp(playerIdx, player, gameState) {
    const hand = player.zones.hand;

    // First try to play a land if we haven't this turn
    if (!player.aiLandPlayedThisTurn) {
      const landIdx = hand.findIndex(c => MacroActionMapper._isLand(c));
      if (landIdx !== -1) {
        const land = hand[landIdx];
        if (!land.imageUrl) land.imageUrl = generateAiCardSVG(land);
        playCardFromHand(playerIdx, landIdx);
        player.aiLandPlayedThisTurn = true;
        MacroActionMapper._log(playerIdx, player,
          `played land <strong>${land.name}</strong>`);
        return true;
      }
    }

    // Then try ramp spells (mana rocks, rampant growth effects)
    const rampSpells = hand.filter(c =>
      MacroActionMapper._looksLikeRamp(c)
    );

    if (rampSpells.length === 0) return false;

    rampSpells.sort((a, b) =>
      MacroActionMapper._cmc(a) - MacroActionMapper._cmc(b)
    );

    for (const card of rampSpells) {
      if (MacroActionMapper._canAfford(playerIdx, card)) {
        const idx = hand.indexOf(card);
        if (idx !== -1) {
          if (!card.imageUrl) card.imageUrl = generateAiCardSVG(card);
          playCardFromHand(playerIdx, idx);
          MacroActionMapper._log(playerIdx, player,
            `cast ramp <strong>${card.name}</strong>`);
          return true;
        }
      }
    }
    return false;
  }

  // ── Cast Commander ────────────────────────────────────────

  static _castCommander(playerIdx, player, gameState) {
    if (player.zones.command.length === 0) return false;

    const result = typeof aiTryCastCommander === 'function'
      ? aiTryCastCommander(playerIdx)
      : false;

    if (result) {
      MacroActionMapper._log(playerIdx, player,
        `cast commander from command zone`);
    }
    return result;
  }

  // ── Attack Opponent ───────────────────────────────────────

  static _attackOpponent(playerIdx, player, gameState) {
    if (typeof aiDeclareAttacks === 'function') {
      aiDeclareAttacks(playerIdx);
      MacroActionMapper._log(playerIdx, player,
        `declaring attacks`);
      return true;
    }
    return false;
  }

  // ── Helper Methods ────────────────────────────────────────

  static _isLand(card) {
    if (!card) return false;
    if (card.typeLine && card.typeLine.toLowerCase().includes('land')) return true;
    if (card.type_line && card.type_line.toLowerCase().includes('land')) return true;
    return typeof aiIsLand === 'function' ? aiIsLand(card) : false;
  }

  static _cmc(card) {
    if (!card) return 0;
    if (typeof card.cmc === 'number') return card.cmc;
    if (typeof aiGetCmc === 'function') return aiGetCmc(card);
    return 0;
  }

  static _canAfford(playerIdx, card) {
    if (!gameState) return false;
    const available = typeof aiCountUntappedLands === 'function'
      ? aiCountUntappedLands(playerIdx)
      : 0;
    return available >= MacroActionMapper._cmc(card);
  }

  static _creatureScore(card) {
    let score = MacroActionMapper._cmc(card) * 2;
    const text = (card.oracleText || card.oracle_text || '').toLowerCase();
    if (text.includes('draw')) score += 3;
    if (text.includes('destroy')) score += 3;
    if (text.includes('flying')) score += 2;
    if (text.includes('trample')) score += 2;
    if (text.includes('haste')) score += 3;
    return score;
  }

  static _looksLikeRemoval(card) {
    const text = (card.oracleText || card.oracle_text || '').toLowerCase();
    return text.includes('destroy') || text.includes('exile') ||
      text.includes('damage to') || text.includes('-x/-x') ||
      text.includes('return target');
  }

  static _looksLikeDraw(card) {
    const text = (card.oracleText || card.oracle_text || '').toLowerCase();
    return text.includes('draw') && !MacroActionMapper._isLand(card);
  }

  static _looksLikeRamp(card) {
    const text = (card.oracleText || card.oracle_text || '').toLowerCase();
    const type = (card.typeLine || card.type_line || '').toLowerCase();
    return (text.includes('add {') || text.includes('search your library for a basic land') ||
      text.includes('land onto the battlefield') ||
      (type.includes('artifact') && text.includes('add')));
  }

  static _log(playerIdx, player, message, confidence) {
    const confStr = confidence
      ? ` <span style="color:var(--color-text-faint)">(${Math.round(confidence * 100)}% conf.)</span>`
      : '';
    addLogEntry(
      `\u{1F9E0} <strong>${player.name}</strong> ${message}${confStr} [ML]`
    );
  }
}

// ============================================================
// DECK SOURCE CLIENT
// ============================================================

class DeckSourceClient {
  constructor(connector) {
    this.connector = connector;
    this._preconCache = null;
    this._preconCacheTime = 0;
    this._cacheTtlMs = 5 * 60 * 1000; // 5 minutes
  }

  /**
   * Fetch precon decks from the backend.
   * Returns array: [{ fileName, deckName, commander, colors, set, ... }]
   */
  async fetchPrecons(forceRefresh = false) {
    if (!this.connector.connected) return [];

    // Check cache
    if (!forceRefresh && this._preconCache &&
        (Date.now() - this._preconCacheTime) < this._cacheTtlMs) {
      return this._preconCache;
    }

    try {
      const data = await this.connector._get('/api/lab/precons');
      this._preconCache = data.precons || [];
      this._preconCacheTime = Date.now();
      return this._preconCache;
    } catch (e) {
      console.warn('[DeckSourceClient] Failed to fetch precons:', e);
      return [];
    }
  }

  /**
   * Fetch EDHREC recommendations for a commander.
   */
  async fetchEdhrecDecks(commanderName) {
    if (!this.connector.connected) return [];
    try {
      const data = await this.connector._get(
        `/api/deckgen/templates?commander=${encodeURIComponent(commanderName)}`
      );
      return data.templates || [];
    } catch (e) {
      return [];
    }
  }

  /**
   * Get deck content (card list) for a specific precon.
   */
  async fetchPreconDeck(fileName) {
    if (!this.connector.connected) return null;
    try {
      const data = await this.connector._get(
        `/api/lab/precons/deck?fileName=${encodeURIComponent(fileName)}`
      );
      return data;
    } catch (e) {
      return null;
    }
  }
}

// ============================================================
// GLOBAL SINGLETON INSTANCES
// ============================================================

const aiBridgeConnector = new BackendConnector();
const aiBridgeGameState = new GameStateBridge(aiBridgeConnector);
const aiBridgeDeckSource = new DeckSourceClient(aiBridgeConnector);

// Export to window for use by engine.js and ui.js
window.AIBridge = {
  VERSION: AI_BRIDGE_VERSION,
  config: AI_BRIDGE_CONFIG,
  connector: aiBridgeConnector,
  gameState: aiBridgeGameState,
  deckSource: aiBridgeDeckSource,
  MacroActionMapper: MacroActionMapper,

  /**
   * Convenience: initialize the bridge and report status.
   */
  async init() {
    const status = await aiBridgeConnector.initialize();
    if (status.connected) {
      console.log(
        `[AI Bridge] Connected to Commander-AI-Lab backend` +
        (status.modelLoaded ? ' (ML model loaded)' : ' (ML model not loaded)')
      );
    } else {
      console.log('[AI Bridge] Backend not available \u2014 using local AI only');
    }
    return status;
  },
};
