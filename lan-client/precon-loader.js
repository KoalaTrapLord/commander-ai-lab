/**
 * precon-loader.js
 * Handles loading precon .dck files from the backend into the lan-client simulator.
 * Depends on: engine.js (gameState, initGame, drawCard, addLogEntry, renderPlayerPanels)
 *             ai-bridge.js (AIBridge.deckSource.fetchPreconDeck)
 *             ui.js (setupDeckChoices, setupPlayerCount, setupStartingLife)
 */

'use strict';

// ============================================================
// startGameWithDecks
// Called by ui.js startGame() when players have selected precon decks.
// Initialises the game state first, then async-loads each player's deck.
// ============================================================
async function startGameWithDecks() {
  // Collect player names from the setup form
  const playerNames = [];
  for (let i = 0; i < (setupPlayerCount || 4); i++) {
    const inp = document.getElementById('player-name-' + i);
    playerNames.push(inp && inp.value.trim() ? inp.value.trim() : 'Player ' + (i + 1));
  }

  // Boot the game with empty zones first so the battlefield renders immediately
  initGame(setupPlayerCount || 4, playerNames, setupStartingLife || 40);

  // Now async-fill each player's zones from their chosen precon
  const choices = typeof setupDeckChoices !== 'undefined' ? setupDeckChoices : {};
  const loadPromises = Object.entries(choices).map(async ([idxStr, choice]) => {
    const playerIdx = parseInt(idxStr, 10);
    if (choice.type !== 'precon' || !choice.preconId) return;

    try {
      // Ensure fileName always ends with .dck
      const fileName = choice.preconId.endsWith('.dck')
        ? choice.preconId
        : choice.preconId + '.dck';

      const data = await AIBridge.deckSource.fetchPreconDeck(fileName);
      if (!data || !data.decklist) {
        addLogEntry('\u26A0 Could not load deck for Player ' + (playerIdx + 1) + ' (no decklist returned)');
        return;
      }

      loadPreconDeckFromDck(playerIdx, data.decklist, choice.preconId);
    } catch (e) {
      console.warn('[precon-loader] Failed to load deck for player', playerIdx, e);
      addLogEntry('\u26A0 Deck load failed for Player ' + (playerIdx + 1) + ': ' + e.message);
    }
  });

  await Promise.all(loadPromises);

  // Refresh the full UI after all decks are loaded
  if (typeof renderPlayerPanels === 'function') renderPlayerPanels();
  if (typeof updateActivePlayerHighlight === 'function') updateActivePlayerHighlight();
}


// ============================================================
// loadPreconDeckFromDck
// Parses a Forge-format .dck file string and populates a player's zones.
//
// Forge .dck format:
//   [metadata]
//   Name=Deck Name
//   [Commander]
//   1 Lathril, Blade of the Elves
//   [Main]
//   1 Sol Ring
//   ...
// ============================================================
function loadPreconDeckFromDck(playerIdx, dckContent, deckLabel) {
  if (!gameState) return;
  const player = gameState.players[playerIdx];
  if (!player) return;

  let commander = '';
  let section = '';
  const mainCards = [];

  for (const rawLine of dckContent.split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('//')) continue;

    // Section headers: [Commander], [Main], [Sideboard], [metadata]
    if (line.startsWith('[') && line.endsWith(']')) {
      section = line.slice(1, -1);
      continue;
    }

    // Skip metadata key=value lines
    if (line.includes('=') && !line.match(/^\d/)) continue;

    // Card lines: "1 Sol Ring" or "1 Sol Ring|ELD"
    const m = line.match(/^(\d+)\s+(.+?)(?:\|.*)?$/);
    if (!m) continue;

    const qty = parseInt(m[1], 10);
    const name = m[2].trim();

    if (section === 'Commander') {
      commander = name;
    } else if (section === 'Main') {
      for (let q = 0; q < qty; q++) {
        mainCards.push(name);
      }
    }
    // Sideboard is ignored for Commander
  }

  // Clear existing zones before populating
  player.zones.command = [];
  player.zones.library = [];
  player.zones.hand = [];
  player.zones.graveyard = [];
  player.zones.exile = [];

  // Populate command zone
  if (commander) {
    player.zones.command.push({
      id: 'cmd-' + playerIdx + '-' + Date.now(),
      name: commander,
      imageUrl: '',        // Scryfall fetch can enrich this later
      typeLine: 'Legendary Creature',
      oracleText: '',
      manaCost: '',
    });
    player.commanderCardName = commander;
  }

  // Populate library
  for (const cardName of mainCards) {
    player.zones.library.push({
      id: 'lib-' + playerIdx + '-' + cardName + '-' + Math.random().toString(36).slice(2, 6),
      name: cardName,
      imageUrl: '',
      typeLine: '',
      oracleText: '',
      manaCost: '',
    });
  }

  // Shuffle library (Fisher-Yates)
  const lib = player.zones.library;
  for (let i = lib.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [lib[i], lib[j]] = [lib[j], lib[i]];
  }

  // Draw opening hand (7 cards)
  for (let d = 0; d < 7 && lib.length > 0; d++) {
    player.zones.hand.push(lib.shift());
  }

  // Update UI for this player
  if (typeof updateZoneCountsForPlayer === 'function') updateZoneCountsForPlayer(playerIdx);
  if (typeof renderCommanderZone === 'function') renderCommanderZone(playerIdx);
  if (typeof renderHandZone === 'function') renderHandZone(playerIdx);

  const label = deckLabel ? deckLabel.replace('.dck', '') : 'Unknown Deck';
  addLogEntry(
    '\uD83C\uDCCF <strong>' + player.name + '</strong> loaded: <em>' + label + '</em>' +
    (commander ? ' — Commander: <strong>' + commander + '</strong>' : '') +
    ' (' + lib.length + ' in library, 7 in hand)'
  );
}
