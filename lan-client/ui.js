/**
 * MTG Commander Simulator — ui.js
 * All UI rendering functions adapted for the 4-quadrant battlefield layout.
 * This file overrides/extends DOM-touching functions from engine.js.
 * ============================================================
 */

'use strict';

// ============================================================
// GLOBAL UI STATE
// ============================================================
let zoneModalPlayerId = null;
let activeZoneTab = 'graveyard';
let _zoneCardCtx = null;
let undoHistoryVisible = false;
let aiTurnActive = false;
let floatingPreviewTimeout = null;

// ============================================================
// LOG SYSTEM (override engine stub)
// ============================================================
const _logEntries = [];

function addLogEntry(text, category) {
  const entry = { text, category: category || 'general', ts: Date.now() };
  _logEntries.push(entry);
  // Keep last 500 entries
  if (_logEntries.length > 500) _logEntries.shift();
  // Show as floating log entry on the battlefield
  addFloatingLogEntry(text, category);
}

function addFloatingLogEntry(text, category) {
  const floatingLog = document.getElementById('floating-log');
  if (!floatingLog) return;
  const entry = document.createElement('div');
  entry.className = 'floating-log-entry';
  entry.innerHTML = text;
  floatingLog.appendChild(entry);
  // Remove old entries
  while (floatingLog.children.length > 5) {
    floatingLog.removeChild(floatingLog.firstChild);
  }
  // Fade out after 4 seconds
  setTimeout(() => {
    entry.style.opacity = '0';
    entry.style.transition = 'opacity 0.6s';
    setTimeout(() => { if (entry.parentNode) entry.remove(); }, 700);
  }, 4000);
}

// ============================================================
// LIFE COUNTER RENDERING (4-quadrant)
// ============================================================
function updateLifeCounterDisplay(playerId) {
  if (!gameState) return;
  const player = gameState.players[playerId];
  if (!player) return;
  const el = document.getElementById('life-' + playerId);
  if (el) el.textContent = player.life;
  // Also update poison
  const poisonEl = document.getElementById('poison-' + playerId);
  if (poisonEl) {
    poisonEl.textContent = player.poison > 0 ? player.poison + ' poison' : '';
    poisonEl.style.display = player.poison > 0 ? 'block' : 'none';
  }
  // Update player label with commander name
  const cmdNameEl = document.getElementById('cmd-name-' + playerId);
  if (cmdNameEl && player.commanderCardName) {
    cmdNameEl.textContent = player.commanderCardName;
  }
}

// Called by engine's setLife
function setLife(playerId, newLife) {
  if (!gameState) return;
  pushUndoState();
  const player = gameState.players[playerId];
  if (!player) return;
  const oldLife = player.life;
  player.life = newLife;
  updateLifeCounterDisplay(playerId);
  const diff = newLife - oldLife;
  const sign = diff > 0 ? '+' : '';
  addLogEntry('<strong>' + player.name + '</strong> life: ' + oldLife + ' → <strong>' + newLife + '</strong> (' + sign + diff + ')');
  if (diff > 0) fireBattlefieldTriggers('life_gain');
  else if (diff < 0) fireBattlefieldTriggers('life_loss');
  if (newLife <= 0 && !player.eliminated) eliminatePlayer(playerId, 'life total reached 0');
  checkStateBasedActions();
  // Highlight active player quadrant
  updateActivePlayerHighlight();
}

// ============================================================
// ACTIVE PLAYER HIGHLIGHT
// ============================================================
function updateActivePlayerHighlight() {
  if (!gameState) return;
  for (let i = 0; i < 4; i++) {
    const area = document.querySelector('.player-area.p' + (i + 1));
    if (area) {
      area.classList.toggle('active-player', gameState.currentPlayerIndex === i);
    }
  }
  // Update active player indicator in top bar
  const indi = document.getElementById('active-player-indicator');
  if (indi && gameState.players[gameState.currentPlayerIndex]) {
    const p = gameState.players[gameState.currentPlayerIndex];
    indi.innerHTML =
      '<span class="active-player-dot" style="background:' + p.color + '"></span>' +
      p.name + "'s Turn";
  }
  // Update turn display
  const turnEl = document.getElementById('turn-counter');
  if (turnEl) turnEl.innerHTML = 'Turn <span>' + (gameState.turnNumber || 1) + '</span>';
}

// ============================================================
// RENDER PLAYER PANELS (adapted for 4-quadrant — updates zones/labels)
// ============================================================
function renderPlayerPanels() {
  if (!gameState) return;
  gameState.players.forEach((player, idx) => {
    updateLifeCounterDisplay(idx);
    updateZoneCountsForPlayer(idx);
    renderCommanderZone(idx);
    renderHandZone(idx);
  });
  updateActivePlayerHighlight();
}

function updateManaPoolBadge(playerIdx) {
  // Future: show mini mana pool indicators on each player's area
}

function updateZoneCountsForPlayer(playerIdx) {
  if (!gameState) return;
  const player = gameState.players[playerIdx];
  if (!player) return;
  const pNum = playerIdx + 1;

  // Update library count
  const libCount = document.getElementById('lib-count-' + pNum);
  if (libCount) libCount.textContent = player.zones.library.length;

  // Update exile count
  const exCount = document.getElementById('exile-count-' + pNum);
  if (exCount) {
    exCount.textContent = player.zones.exile.length;
    exCount.style.display = player.zones.exile.length > 0 ? 'block' : 'none';
  }

  // Update graveyard count
  const gvCount = document.getElementById('gv-count-' + pNum);
  if (gvCount) {
    gvCount.textContent = player.zones.graveyard.length;
    gvCount.style.display = player.zones.graveyard.length > 0 ? 'block' : 'none';
  }

  // Update hand count
  const handCount = document.getElementById('hand-count-' + pNum);
  if (handCount) handCount.textContent = player.zones.hand.length;
}

function updatePlayerZones() {
  if (!gameState) return;
  gameState.players.forEach((_, idx) => {
    updateZoneCountsForPlayer(idx);
    renderHandZone(idx);
    renderCommanderZone(idx);
  });
}

// ============================================================
// COMMANDER ZONE RENDERING
// ============================================================
function renderCommanderZone(playerIdx) {
  if (!gameState) return;
  const player = gameState.players[playerIdx];
  if (!player) return;
  const pNum = playerIdx + 1;
  const zoneEl = document.getElementById('cmd-zone-' + pNum);
  if (!zoneEl) return;

  const cmdCards = player.zones.command || [];
  if (cmdCards.length > 0) {
    const cmdCard = cmdCards[0];
    if (cmdCard.imageUrl) {
      zoneEl.innerHTML =
        '<img src="' + cmdCard.imageUrl + '" alt="' + (cmdCard.name || 'Commander') + '" ' +
        'style="width:100%;height:100%;object-fit:cover;border-radius:6px;" ' +
        'onmouseenter="showFloatingCardPreview(\'' + (cmdCard.imageUrl || '').replace(/'/g, "\\'") + '\', event, {name:\'' + (cmdCard.name || '').replace(/'/g, "\\'") + '\', typeLine:\'' + (cmdCard.typeLine || '').replace(/'/g, "\\'") + '\'})" ' +
        'onmousemove="positionFloatingPreview(event)" ' +
        'onmouseleave="hideFloatingCardPreview()" ' +
        'draggable="false" />';
      // Count badge
      if (player.commanderCastCount > 0) {
        zoneEl.innerHTML += '<span class="card-count" style="background:rgba(200,168,67,0.7);color:#000;">' + (player.commanderCastCount) + 'x</span>';
      }
    } else {
      zoneEl.innerHTML =
        '<span class="zone-icon" style="color:var(--p' + pNum + '-text)">&#x1F451;</span>' +
        '<span class="zone-name">Commander</span>' +
        '<span class="card-count">' + cmdCards.length + '</span>';
    }
  } else {
    zoneEl.innerHTML =
      '<span class="zone-icon" style="color:var(--p' + pNum + '-text)">&#x1F451;</span>' +
      '<span class="zone-name">Commander</span>';
  }
}

// ============================================================
// HAND ZONE RENDERING (thumbnails in zone.hand)
// ============================================================
function renderHandZone(playerIdx) {
  if (!gameState) return;
  const player = gameState.players[playerIdx];
  if (!player) return;
  const pNum = playerIdx + 1;
  const handEl = document.getElementById('hand-zone-' + pNum);
  if (!handEl) return;

  const hand = player.zones.hand || [];

  // Update count badge
  const countEl = document.getElementById('hand-count-' + pNum);
  if (countEl) countEl.textContent = hand.length;

  if (hand.length === 0) {
    handEl.innerHTML =
      '<span class="zone-icon" style="color:var(--p' + pNum + '-text)">&#x1F0CF;</span>' +
      '<span class="zone-name">Hand (0)</span>';
    return;
  }

  // Render thumbnails
  let thumbsHtml = '';
  const maxShow = Math.min(hand.length, 7); // limit thumbnails
  for (let i = 0; i < maxShow; i++) {
    const card = hand[i];
    const imgSrc = card.imageUrl || '';
    const escapedName = (card.name || '').replace(/'/g, "\\'");
    const escapedType = (card.typeLine || '').replace(/'/g, "\\'");
    if (imgSrc) {
      thumbsHtml +=
        '<div class="hand-thumb" ' +
        'onclick="openZoneModal(' + playerIdx + ')" ' +
        'onmouseenter="showFloatingCardPreview(\'' + imgSrc.replace(/'/g, "\\'") + '\',event,{name:\'' + escapedName + '\',typeLine:\'' + escapedType + '\'})" ' +
        'onmousemove="positionFloatingPreview(event)" ' +
        'onmouseleave="hideFloatingCardPreview()">' +
        '<img src="' + imgSrc + '" alt="' + (card.name || '') + '" draggable="false" />' +
        '</div>';
    } else {
      thumbsHtml += '<div class="hand-thumb" onclick="openZoneModal(' + playerIdx + ')" style="background:rgba(255,255,255,0.08);display:flex;align-items:center;justify-content:center;font-size:8px;color:rgba(255,255,255,0.4);">' +
        (card.name || '?').substring(0, 4) + '</div>';
    }
  }

  if (hand.length > maxShow) {
    thumbsHtml += '<div class="hand-thumb" onclick="openZoneModal(' + playerIdx + ')" style="background:rgba(255,255,255,0.05);display:flex;align-items:center;justify-content:center;font-size:9px;color:rgba(255,255,255,0.4);">+' + (hand.length - maxShow) + '</div>';
  }

  handEl.innerHTML = thumbsHtml;
}

// ============================================================
// RENDER BATTLEFIELD CARD (adapted for quadrant battle-zones)
// ============================================================
function renderBattlefieldCard(cardData) {
  // Target the player's battle-zone div
  const pNum = cardData.ownerIndex + 1;
  const battleZone = document.getElementById('battle-zone-' + pNum);
  if (!battleZone) {
    // Fallback: try old-style battlefield
    const bf = document.getElementById('battlefield');
    if (!bf) return;
  }
  const container = battleZone || document.getElementById('battlefield');

  // Remove existing card element if re-rendering
  const existing = document.getElementById('bc-' + cardData.id);
  if (existing) existing.remove();

  const card = document.createElement('div');
  card.className = 'battlefield-card';
  card.id = 'bc-' + cardData.id;
  card.style.left = (cardData.x || 10) + 'px';
  card.style.top = (cardData.y || 10) + 'px';

  const playerColor = (gameState.players[cardData.ownerIndex] || {}).color || 'transparent';
  card.style.borderColor = playerColor;

  if (cardData.tapped) card.classList.add('tapped');
  if (cardData.faceDown) card.classList.add('face-down');
  if (typeof hasSummoningSickness === 'function' && hasSummoningSickness(cardData)) {
    card.classList.add('summoning-sick');
  }
  if (cardData.isToken) card.classList.add('token-glow');

  // Keyword badges HTML
  let kwBadgeHtml = '';
  if (typeof getKeywordBadges === 'function') {
    const kwBadges = getKeywordBadges(cardData);
    if (kwBadges && kwBadges.length > 0) {
      kwBadgeHtml = '<div class="kw-badge-strip">';
      kwBadges.forEach(b => {
        kwBadgeHtml += '<span class="kw-badge" style="background:' + b.color + '" title="' + b.name + '">' + b.icon + '</span>';
      });
      kwBadgeHtml += '</div>';
    }
  }

  // Protection badge
  let protBadge = '';
  if (typeof getBattlefieldCardProtectionBadge === 'function') {
    protBadge = getBattlefieldCardProtectionBadge(cardData) || '';
  }

  const imgUrl = cardData.imageUrl || '';
  const altName = (cardData.name || 'Card').replace(/"/g, '&quot;');

  card.innerHTML =
    protBadge +
    '<img src="' + imgUrl + '" alt="' + altName + '" draggable="false" loading="lazy"/>' +
    '<div class="card-owner-bar" style="background:' + playerColor + '"></div>' +
    kwBadgeHtml;

  // Counter badges
  if (cardData.counters) {
    const cTypes = Object.keys(cardData.counters).filter(k => cardData.counters[k] > 0);
    if (cTypes.length > 0) {
      const strip = document.createElement('div');
      strip.className = 'card-counters-strip';
      cTypes.forEach(cType => {
        const cCount = cardData.counters[cType];
        const ct = (typeof COUNTER_TYPES !== 'undefined' && COUNTER_TYPES[cType]) ||
          { icon: '\u25CF', color: '#9ca3af', label: cType };
        const badge = document.createElement('span');
        badge.className = 'card-counter-badge';
        badge.style.cssText = 'background:' + ct.color + ';color:#fff;';
        badge.title = cCount + ' ' + ct.label;
        if (cType === '+1/+1') badge.textContent = '+' + cCount + '/+' + cCount;
        else if (cType === '-1/-1') badge.textContent = '-' + cCount + '/-' + cCount;
        else badge.textContent = ct.icon + cCount;
        strip.appendChild(badge);
      });
      card.appendChild(strip);
    }
  }

  // Damage badge
  if (cardData.damageMarked && cardData.damageMarked > 0) {
    const dmgBadge = document.createElement('div');
    dmgBadge.className = 'damage-badge';
    dmgBadge.textContent = cardData.damageMarked;
    card.appendChild(dmgBadge);
  }

  // Event listeners — use both for compatibility (Comet: inline onclick already on container)
  card.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    if (cardData.attachedTo) return;
    e.preventDefault();
    isDraggingBattlefieldCard = true;
    draggedCardId = cardData.id;
    const rect = card.getBoundingClientRect();
    dragOffset.x = e.clientX - rect.left;
    dragOffset.y = e.clientY - rect.top;
    card.style.zIndex = '100';
    card.style.transition = 'none';
  });

  card.addEventListener('dblclick', e => {
    e.preventDefault();
    toggleTap(cardData.id);
  });

  card.addEventListener('contextmenu', e => {
    e.preventDefault();
    showContextMenu(e.clientX, e.clientY, cardData.id);
  });

  card.addEventListener('click', e => {
    if (!gameState) return;
    if (typeof stackPickMode !== 'undefined' && stackPickMode) {
      handleStackPickClick(cardData.id);
      e.stopPropagation();
      return;
    }
    if (typeof equipPickMode !== 'undefined' && equipPickMode) {
      handleEquipPickClick(cardData.id);
      e.stopPropagation();
      return;
    }
    // Combat attacker/blocker clicks
    const combat = gameState.combat;
    if (combat && combat.phase === 'declaring-attackers') {
      if (cardData.ownerIndex === gameState.currentPlayerIndex && !cardData.tapped) {
        toggleAttacker(cardData.id);
        e.stopPropagation();
      }
    } else if (combat && combat.phase === 'declaring-blockers') {
      if (!cardData.tapped && combat.pendingBlockerFor !== null) {
        toggleBlocker(cardData.id, combat.pendingBlockerFor);
        e.stopPropagation();
      } else {
        const asAttacker = combat.attackers && combat.attackers.find(a => a.cardId === cardData.id);
        if (asAttacker) {
          combat.pendingBlockerFor = cardData.id;
          refreshCombatOverlay();
          e.stopPropagation();
        }
      }
    }
  });

  // Long press for context menu (touch)
  let _lpTimer = null;
  card.addEventListener('touchstart', e => {
    _lpTimer = setTimeout(() => {
      const t = e.touches[0];
      showContextMenu(t.clientX, t.clientY, cardData.id);
    }, 600);
  });
  card.addEventListener('touchend', () => clearTimeout(_lpTimer));
  card.addEventListener('touchmove', () => clearTimeout(_lpTimer));

  card.addEventListener('mouseenter', e => {
    if (!isDraggingBattlefieldCard) {
      if (cardData.stackGroupId && typeof isStackLeader === 'function' && isStackLeader(cardData)) {
        fanOutStack(cardData.stackGroupId);
      }
      showFloatingCardPreview(cardData.imageUrl, e, {
        name: cardData.name,
        typeLine: cardData.typeLine,
        oracleText: cardData.oracleText,
        manaCost: cardData.manaCost || '',
        power: cardData.power,
        toughness: cardData.toughness,
        pt: cardData.pt,
        loyalty: cardData.loyalty,
        _bfCard: cardData
      });
    }
  });

  card.addEventListener('mousemove', e => {
    if (!isDraggingBattlefieldCard) positionFloatingPreview(e);
  });

  card.addEventListener('mouseleave', () => {
    hideFloatingCardPreview();
  });

  container.appendChild(card);
}

// Drag tracking for battlefield cards
document.addEventListener('mousemove', e => {
  if (!isDraggingBattlefieldCard || draggedCardId === null) return;
  hideFloatingCardPreview();

  const cardData = gameState && gameState.battlefieldCards.find(c => c.id === draggedCardId);
  if (!cardData) return;

  const pNum = cardData.ownerIndex + 1;
  const battleZone = document.getElementById('battle-zone-' + pNum);
  if (!battleZone) return;

  const rect = battleZone.getBoundingClientRect();
  let newX = e.clientX - rect.left - dragOffset.x;
  let newY = e.clientY - rect.top - dragOffset.y;

  newX = Math.max(0, Math.min(rect.width - 80, newX));
  newY = Math.max(0, Math.min(rect.height - 105, newY));

  cardData.x = newX;
  cardData.y = newY;

  const cardEl = document.getElementById('bc-' + draggedCardId);
  if (cardEl) {
    cardEl.style.left = newX + 'px';
    cardEl.style.top = newY + 'px';
  }

  if (cardData.attachments && cardData.attachments.length > 0) {
    moveAttachmentsWithCreature(cardData.id);
  }
});

document.addEventListener('mouseup', e => {
  if (!isDraggingBattlefieldCard) return;
  isDraggingBattlefieldCard = false;
  const droppedId = draggedCardId;
  const cardEl = document.getElementById('bc-' + droppedId);
  if (cardEl) {
    cardEl.style.zIndex = '';
    cardEl.style.transition = '';
  }
  draggedCardId = null;

  // Shift+drop stacking
  if (e.shiftKey && droppedId && gameState) {
    const droppedCard = gameState.battlefieldCards.find(c => c.id === droppedId);
    if (droppedCard && typeof createStack === 'function') {
      const threshold = 40;
      let closestCard = null, closestDist = Infinity;
      gameState.battlefieldCards.forEach(other => {
        if (other.id === droppedId) return;
        if (other.stackGroupId && !isStackLeader(other)) return;
        const dx = (other.x || 0) - (droppedCard.x || 0);
        const dy = (other.y || 0) - (droppedCard.y || 0);
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < threshold && dist < closestDist) {
          closestDist = dist;
          closestCard = other;
        }
      });
      if (closestCard) createStack(closestCard.id, droppedId);
    }
  }
});

// ============================================================
// PHASE TRACKER
// ============================================================
function renderPhaseTracker() {
  if (!gameState) return;
  const track = document.getElementById('phase-track');
  if (!track) return;

  const currentPhase = PHASES[gameState.currentPhaseIndex] || PHASES[0];
  let html = '';

  PHASES.forEach((phase, idx) => {
    const isActive = idx === gameState.currentPhaseIndex;
    const isDone = idx < gameState.currentPhaseIndex;
    let cls = 'phase-step';
    if (isActive) cls += ' active';
    if (isDone) cls += ' done';

    let style = '';
    if (isActive) {
      style = 'style="background:' + hexToRgba(phase.color || '#5b8dd9', 0.25) + ';box-shadow:inset 0 0 0 1px ' + hexToRgba(phase.color || '#5b8dd9', 0.4) + '"';
    }

    // If in combat and this is the combat phase, show current combat sub-phase
    let label = phase.short;
    if (idx === 2 && gameState.inCombat) {
      const combatPhase = COMBAT_PHASES[gameState.combatPhaseIndex] || COMBAT_PHASES[0];
      label = combatPhase.short;
    }

    html += '<div class="' + cls + '" title="' + phase.tip + '" ' + style + ' onclick="handlePhaseClick(' + idx + ')">';
    html += '<span class="phase-step-icon">' + (phase.icon || '') + '</span>';
    html += '<span class="phase-step-label">' + label + '</span>';
    html += '</div>';

    if (idx < PHASES.length - 1) {
      html += '<div class="phase-connector' + (isDone ? ' done' : '') + '"></div>';
    }
  });

  track.innerHTML = html;
}

function handlePhaseClick(phaseIdx) {
  // Just provide info about the phase, don't jump to it
  if (!gameState) return;
  const phase = PHASES[phaseIdx];
  if (phase) addLogEntry('Phase info: <strong>' + phase.label + '</strong> — ' + phase.tip);
}

function updateTurnDisplay() {
  if (!gameState) return;
  const turnEl = document.getElementById('turn-counter');
  if (turnEl) turnEl.innerHTML = 'Turn <span>' + (gameState.turnNumber || 1) + '</span>';
  updateActivePlayerHighlight();
  renderPhaseTracker();
}

function updateStormCounter() {
  if (!gameState) return;
  const storm = gameState.stormCount || 0;
  const badge = document.getElementById('storm-badge');
  if (badge) {
    badge.textContent = 'Storm: ' + storm;
    badge.style.display = storm > 0 ? 'block' : 'none';
  }
}

// ============================================================
// MANA POOL DISPLAY
// ============================================================
function renderManaPool(playerIdx) {
  if (!gameState) return;
  const pool = getManaPool(playerIdx !== undefined ? playerIdx : gameState.currentPlayerIndex);
  const display = document.getElementById('mana-pool-display');
  if (!display) return;

  const colors = ['W', 'U', 'B', 'R', 'G', 'C'];
  let html = '<span class="mana-pool-label">MANA:</span>';
  let hasAny = false;

  colors.forEach(c => {
    if (pool[c] > 0) {
      hasAny = true;
      html += '<span class="mana-pip mana-' + c + '" title="' + getManaColorName(c) + ': ' + pool[c] + '">' + pool[c] + '</span>';
    }
  });

  if (!hasAny) {
    html += '<span class="mana-empty">Empty</span>';
  }

  html += '<button class="mana-pool-clear-btn" onclick="clearManaPool(' + gameState.currentPlayerIndex + ')" title="Clear mana pool">x</button>';
  display.innerHTML = html;
  display.style.display = gameState.inGame ? 'flex' : 'none';
}

// ============================================================
// CONTEXT MENU
// ============================================================
let contextMenuTargetId = null;

function showContextMenu(x, y, cardId) {
  contextMenuTargetId = cardId;
  const menu = document.getElementById('context-menu');
  if (!menu) return;

  menu.classList.add('visible');

  const cardData = gameState && gameState.battlefieldCards.find(c => c.id === cardId);
  const _isEquip = cardData && typeof isEquipment === 'function' && isEquipment(cardData);
  const _isAuraCard = cardData && typeof isAura === 'function' && isAura(cardData);
  const _isPlaneswalker = cardData && cardData.typeLine && /planeswalker/i.test(cardData.typeLine);
  const hasAbilities = cardData && typeof parseActivatedAbilities === 'function' && parseActivatedAbilities(cardData).length > 0;

  menu.innerHTML =
    '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();toggleTap(id)})()">&#x27F3; Tap / Untap</button>' +
    '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();toggleFaceDown(id)})()">&#x25FB; Face Down/Up</button>' +
    '<div class="context-menu-divider"></div>' +
    '<div class="context-menu-counter-row">' +
      '<button class="context-menu-counter-btn plus" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();addCounter(id,\'+1/+1\')})()" title="+1/+1 counter">+1</button>' +
      '<button class="context-menu-counter-btn minus" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();addCounter(id,\'-1/-1\')})()" title="-1/-1 counter">-1</button>' +
      '<button class="context-menu-item" style="flex:1" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();showCounterPicker(id)})()">Counters...</button>' +
    '</div>' +
    '<div class="context-menu-divider"></div>' +
    (hasAbilities ? '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();showActivatedAbilitiesPanel(id)})()">&#x26A1; Abilities</button>' : '') +
    (_isPlaneswalker ? '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();showPlaneswalkerAbilities(id)})()">&#x25C6; PW Abilities</button>' : '') +
    (_isEquip ? '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();enterEquipPickMode(id)})()">&#x2694; Equip to Creature</button>' : '') +
    '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();enterStackPickMode(id)})()">&#x25A3; Stack With Card</button>' +
    '<div class="context-menu-divider"></div>' +
    '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();moveCardToZone(id,\'graveyard\')})()">&#x2620; To Graveyard</button>' +
    '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();moveCardToZone(id,\'exile\')})()">&#x2B21; To Exile</button>' +
    '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();moveCardToZone(id,\'hand\')})()">&#x270B; Return to Hand</button>' +
    '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();moveCardToLibrary(id,\'top\')})()">&#x1F4DA; Top of Library</button>' +
    '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();moveCardToLibrary(id,\'bottom\')})()">&#x1F4DA; Bottom of Library</button>' +
    '<div class="context-menu-divider"></div>' +
    '<button class="context-menu-item" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();sacrificeCard(id)})()">&#x1F480; Sacrifice</button>' +
    '<button class="context-menu-item danger" onclick="(function(){var id=contextMenuTargetId;hideContextMenu();removeCardFromBattlefield(id)})()">&#x2715; Remove</button>';

  // Position
  const maxX = window.innerWidth - 200;
  const maxY = window.innerHeight - 360;
  menu.style.left = Math.min(x, maxX) + 'px';
  menu.style.top = Math.min(y, maxY) + 'px';
}

function hideContextMenu() {
  const menu = document.getElementById('context-menu');
  if (menu) menu.classList.remove('visible');
}

// Close context menu on outside click
document.addEventListener('click', e => {
  const menu = document.getElementById('context-menu');
  if (menu && !menu.contains(e.target)) hideContextMenu();
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    hideContextMenu();
    if (typeof cancelStackPickMode === 'function') cancelStackPickMode();
    if (typeof cancelEquipPickMode === 'function') cancelEquipPickMode();
    closeZoneModal();
  }
});

// ============================================================
// FLOATING CARD PREVIEW
// ============================================================
function showFloatingCardPreview(imgSrc, e, cardInfo) {
  if (!imgSrc) return;
  const preview = document.getElementById('card-preview');
  if (!preview) return;

  if (floatingPreviewTimeout) {
    clearTimeout(floatingPreviewTimeout);
    floatingPreviewTimeout = null;
  }

  const img = preview.querySelector('img');
  if (img) img.src = imgSrc;

  const infoDiv = preview.querySelector('.card-preview-info');
  if (infoDiv && cardInfo) {
    const nameEl = preview.querySelector('.card-preview-name');
    const typeEl = preview.querySelector('.card-preview-type');
    const oracleEl = preview.querySelector('.card-preview-oracle');
    const ptEl = preview.querySelector('.card-preview-pt');
    if (nameEl) nameEl.textContent = cardInfo.name || '';
    if (typeEl) typeEl.textContent = cardInfo.typeLine || '';
    if (oracleEl) oracleEl.textContent = cardInfo.oracleText || '';
    if (ptEl) {
      const pt = cardInfo.pt || (cardInfo.power && cardInfo.toughness ? cardInfo.power + '/' + cardInfo.toughness : '');
      ptEl.textContent = pt;
    }
    if (cardInfo.name || cardInfo.typeLine || cardInfo.oracleText) {
      infoDiv.style.display = 'block';
    } else {
      infoDiv.style.display = 'none';
    }
  }

  preview.style.display = 'block';
  positionFloatingPreview(e);
}

function positionFloatingPreview(e) {
  const preview = document.getElementById('card-preview');
  if (!preview || preview.style.display === 'none') return;

  const pw = preview.offsetWidth || 220;
  const ph = preview.offsetHeight || 340;
  const ww = window.innerWidth;
  const wh = window.innerHeight;

  let px = e.clientX + 16;
  let py = e.clientY - 20;

  if (px + pw > ww - 10) px = e.clientX - pw - 16;
  if (py + ph > wh - 10) py = wh - ph - 10;
  if (py < 50) py = 50;

  preview.style.left = px + 'px';
  preview.style.top = py + 'px';
}

function hideFloatingCardPreview() {
  floatingPreviewTimeout = setTimeout(() => {
    const preview = document.getElementById('card-preview');
    if (preview) preview.style.display = 'none';
  }, 80);
}

// ============================================================
// ZONE MODAL
// ============================================================
function openZoneModal(playerId, zone) {
  zoneModalPlayerId = playerId;
  activeZoneTab = zone || 'graveyard';
  renderZoneModal();
  const modal = document.getElementById('zone-modal');
  if (modal) modal.classList.add('visible');
}

function closeZoneModal() {
  const modal = document.getElementById('zone-modal');
  if (modal) modal.classList.remove('visible');
  zoneModalPlayerId = null;
  if (_zoneCardCtx) _zoneCardCtx.classList.remove('visible');
}

function switchZoneTab(zone) {
  activeZoneTab = zone;
  renderZoneModal();
}

function renderZoneModal() {
  if (zoneModalPlayerId === null || !gameState) return;
  const player = gameState.players[zoneModalPlayerId];
  if (!player) return;

  const titleEl = document.getElementById('zone-modal-title');
  if (titleEl) titleEl.textContent = player.name + "'s Zones";

  // Render tabs
  const tabsEl = document.getElementById('zone-modal-tabs');
  if (tabsEl) {
    const zones = [
      { key: 'graveyard', icon: '&#x2620;', label: 'Graveyard' },
      { key: 'exile', icon: '&#x2B21;', label: 'Exile' },
      { key: 'command', icon: '&#x1F451;', label: 'Command' },
      { key: 'hand', icon: '&#x270B;', label: 'Hand' },
      { key: 'library', icon: '&#x1F4DA;', label: 'Library' },
    ];

    tabsEl.innerHTML = zones.map(z => {
      const count = (player.zones[z.key] || []).length;
      const isActive = z.key === activeZoneTab;
      return '<button class="zone-tab' + (isActive ? ' active' : '') + '" ' +
        'onclick="switchZoneTab(\'' + z.key + '\')">' +
        z.icon + ' ' + z.label + ' <span class="zone-tab-count">(' + count + ')</span></button>';
    }).join('');
  }

  const body = document.getElementById('zone-modal-body');
  if (!body) return;

  const cards = player.zones[activeZoneTab] || [];

  let actionButtons = '';
  if (activeZoneTab === 'library') {
    actionButtons =
      '<button class="btn btn-cancel" style="font-size:11px;padding:3px 10px;" onclick="shuffleLibrary(' + zoneModalPlayerId + ')">&#x1F500; Shuffle</button>' +
      '<button class="btn btn-cancel" style="font-size:11px;padding:3px 10px;" onclick="drawCard(' + zoneModalPlayerId + ')">&#x1F4E4; Draw</button>' +
      '<button class="btn btn-cancel" style="font-size:11px;padding:3px 10px;" onclick="showScryDialog(' + zoneModalPlayerId + ')">&#x1F52E; Scry</button>' +
      '<button class="btn btn-cancel" style="font-size:11px;padding:3px 10px;" onclick="showMillDialog(' + zoneModalPlayerId + ')">Mill</button>';
  }

  if (cards.length === 0) {
    body.innerHTML =
      (actionButtons ? '<div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;">' + actionButtons + '</div>' : '') +
      '<div class="zone-empty">No cards in ' + activeZoneTab + '.</div>';
    return;
  }

  let gridHtml = '<div class="zone-cards-grid">';
  cards.forEach((card, idx) => {
    const imgSrc = card.imageUrl || '';
    const safeName = (card.name || 'Unknown').replace(/'/g, "\\'").replace(/"/g, '&quot;');
    const safeType = (card.typeLine || '').replace(/'/g, "\\'");
    gridHtml +=
      '<div class="zone-card-thumb" ' +
      'onclick="zmPlayCard(' + zoneModalPlayerId + ',\'' + activeZoneTab + '\',' + idx + ')" ' +
      'oncontextmenu="(function(e){e.preventDefault();showZoneCardCtx(e.clientX,e.clientY,' + zoneModalPlayerId + ',\'' + activeZoneTab + '\',' + idx + ')})(event)" ' +
      (imgSrc ? 'onmouseenter="showFloatingCardPreview(\'' + imgSrc.replace(/'/g, "\\'") + '\',event,{name:\'' + safeName + '\',typeLine:\'' + safeType + '\'})" onmousemove="positionFloatingPreview(event)" onmouseleave="hideFloatingCardPreview()"' : '') +
      '>' +
      (imgSrc ? '<img src="' + imgSrc + '" alt="' + safeName + '" loading="lazy"/>' :
        '<div style="width:100%;aspect-ratio:63/88;background:rgba(255,255,255,0.05);display:flex;align-items:center;justify-content:center;font-size:10px;color:rgba(255,255,255,0.3);padding:4px;text-align:center;">' + safeName + '</div>') +
      '<div class="zone-card-label" style="padding:3px 5px;font-size:9px;color:rgba(255,255,255,0.5);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + (card.name || 'Unknown') + '</div>' +
      '</div>';
  });
  gridHtml += '</div>';

  const infoBar = '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;flex-wrap:wrap;gap:6px;">' +
    '<span style="font-size:12px;color:var(--color-text-muted);"><strong>' + cards.length + '</strong> card' + (cards.length !== 1 ? 's' : '') + '</span>' +
    '<div style="display:flex;gap:5px;flex-wrap:wrap;">' + actionButtons + '</div>' +
    '</div>';

  body.innerHTML = infoBar + gridHtml;
}

// Zone card context menu
function showZoneCardCtx(x, y, playerId, zone, cardIndex) {
  if (_zoneCardCtx) _zoneCardCtx.classList.remove('visible');
  if (!_zoneCardCtx) {
    _zoneCardCtx = document.createElement('div');
    _zoneCardCtx.className = 'zone-card-ctx';
    _zoneCardCtx.id = 'zone-card-ctx';
    _zoneCardCtx.style.cssText =
      'position:fixed;z-index:1100;background:var(--color-surface-raised);' +
      'border:1px solid var(--color-border-strong);border-radius:var(--radius-lg);' +
      'padding:6px;box-shadow:var(--shadow-lg);min-width:180px;';
    document.body.appendChild(_zoneCardCtx);
  }

  const player = gameState && gameState.players[playerId];
  const card = player && player.zones[zone] ? player.zones[zone][cardIndex] : null;
  if (!card) return;

  const items = [
    { icon: '&#x2694;', label: 'Play to Battlefield', action: 'battlefield' },
    { icon: '&#x270B;', label: 'Return to Hand', action: 'hand', skip: zone === 'hand' },
    { divider: true },
    { icon: '&#x2620;', label: 'To Graveyard', action: 'graveyard', skip: zone === 'graveyard' },
    { icon: '&#x2B21;', label: 'To Exile', action: 'exile', skip: zone === 'exile' },
    { icon: '&#x1F451;', label: 'To Command Zone', action: 'command', skip: zone === 'command' },
    { divider: true },
    { icon: '&#x1F4DA;', label: 'Top of Library', action: 'library-top' },
    { icon: '&#x1F4DA;', label: 'Bottom of Library', action: 'library-bottom' },
    { divider: true },
    { icon: '&#x2715;', label: 'Remove from Game', action: 'remove', danger: true },
  ];

  _zoneCardCtx.innerHTML =
    '<div style="padding:4px 8px;font-size:10px;font-weight:700;color:rgba(255,255,255,0.4);border-bottom:1px solid rgba(255,255,255,0.08);margin-bottom:3px;">' +
    (card.name || 'Card') + '</div>';

  items.forEach(item => {
    if (item.skip) return;
    if (item.divider) {
      _zoneCardCtx.innerHTML += '<div style="height:1px;background:var(--color-divider);margin:3px 0;"></div>';
      return;
    }
    _zoneCardCtx.innerHTML +=
      '<button class="context-menu-item' + (item.danger ? ' danger' : '') + '" ' +
      'onclick="(function(){hideZoneCardCtxMenu();handleZmCtxAction(' + playerId + ',\'' + zone + '\',' + cardIndex + ',\'' + item.action + '\')})()">' +
      item.icon + ' ' + item.label + '</button>';
  });

  _zoneCardCtx.style.left = Math.min(x, window.innerWidth - 200) + 'px';
  _zoneCardCtx.style.top = Math.min(y, window.innerHeight - 300) + 'px';
  _zoneCardCtx.classList.add('visible');
  _zoneCardCtx.style.display = 'block';
}

function hideZoneCardCtxMenu() {
  if (_zoneCardCtx) { _zoneCardCtx.classList.remove('visible'); _zoneCardCtx.style.display = 'none'; }
}

function handleZmCtxAction(playerId, zone, cardIndex, action) {
  pushUndoState();
  const player = gameState && gameState.players[playerId];
  if (!player) return;
  const cards = player.zones[zone];
  if (!cards || cardIndex < 0 || cardIndex >= cards.length) return;
  const card = cards[cardIndex];

  if (action === 'battlefield') {
    cards.splice(cardIndex, 1);
    if (zone === 'command' && gameState.rulesEngine && gameState.rulesEngine.commanderTaxEnabled) {
      player.commanderCastCount = (player.commanderCastCount || 0) + 1;
    }
    addCardToBattlefield(card.name, card.imageUrl, card.typeLine, playerId, undefined, undefined, card.oracleText || '',
      { manaCost: card.manaCost || '', power: card.power || '', toughness: card.toughness || '', pt: card.pt || '', cmc: card.cmc || 0, loyalty: card.loyalty || '' });
    addLogEntry('<strong>' + card.name + '</strong> moved from ' + zone + ' to battlefield');
  } else if (action === 'hand') {
    cards.splice(cardIndex, 1);
    player.zones.hand.push(card);
    addLogEntry('<strong>' + card.name + '</strong> returned to ' + player.name + "'s hand");
  } else if (['graveyard', 'exile', 'command'].includes(action)) {
    cards.splice(cardIndex, 1);
    player.zones[action].push(card);
    addLogEntry('<strong>' + card.name + '</strong> moved to ' + action);
  } else if (action === 'library-top') {
    cards.splice(cardIndex, 1);
    player.zones.library.unshift(card);
    addLogEntry('<strong>' + card.name + '</strong> put on top of library');
  } else if (action === 'library-bottom') {
    cards.splice(cardIndex, 1);
    player.zones.library.push(card);
    addLogEntry('<strong>' + card.name + '</strong> put on bottom of library');
  } else if (action === 'remove') {
    cards.splice(cardIndex, 1);
    addLogEntry('<strong>' + card.name + '</strong> removed from game');
  }

  updatePlayerZones();
  renderZoneModal();
  renderHandArea();
}

// ============================================================
// HAND AREA — full hand display (used in hand-area section, NOT the zone thumbnails)
// For the new layout, hand is rendered as thumbnails in the zone.hand element
// ============================================================
function renderHandArea() {
  if (!gameState) return;
  // In the quadrant layout, hand is shown as thumbnails in each player's zone
  gameState.players.forEach((_, idx) => renderHandZone(idx));
}

// ============================================================
// SETUP SCREEN
// ============================================================
function initSetupScreen() {
  let selectedPlayerCount = 4;
  let startingLife = 40;
  const playerColors = [
    { color: '#c0392b', name: 'P1 (Crimson)' },
    { color: '#2980b9', name: 'P2 (Sapphire)' },
    { color: '#27ae60', name: 'P3 (Emerald)' },
    { color: '#d4930d', name: 'P4 (Gold)' },
  ];

  const setupEl = document.getElementById('setup-screen');
  if (!setupEl) return;

  setupEl.innerHTML =
    '<div class="setup-card">' +
    '<div class="setup-title">Commander</div>' +
    '<div class="setup-subtitle">4-Player Battlefield Simulator</div>' +

    '<div class="setup-section">' +
    '<div class="setup-label">Players</div>' +
    '<div class="player-count-btns" id="player-count-btns">' +
    [2, 3, 4].map(n =>
      '<button class="player-count-btn' + (n === 4 ? ' active' : '') + '" onclick="selectPlayerCount(' + n + ')">' + n + '</button>'
    ).join('') +
    '</div>' +
    '</div>' +

    '<div class="setup-section">' +
    '<div class="setup-label">Player Names</div>' +
    '<div class="player-names-grid" id="player-names-grid">' +
    playerColors.map((pc, i) =>
      '<div class="player-name-field" id="player-field-' + i + '">' +
      '<div class="player-color-dot" style="background:' + pc.color + '"></div>' +
      '<input class="player-name-input" id="player-name-' + i + '" type="text" placeholder="' + pc.name + '" value="Player ' + (i + 1) + '" maxlength="20"/>' +
      '</div>'
    ).join('') +
    '</div>' +
    '</div>' +

    '<div class="setup-section">' +
    '<div class="setup-label">AI Opponents</div>' +
    '<div id="ai-toggle-grid" style="display:flex;gap:6px;flex-wrap:wrap;"></div>' +
    '<div id="ai-difficulty-row" style="display:none;margin-top:8px;align-items:center;gap:6px;">' +
    '<span style="font-size:11px;color:rgba(255,255,255,0.5);">Difficulty:</span>' +
    '<button class="ai-diff-btn active" onclick="window._setAiDiff(this,\'easy\')" data-diff="easy" style="font-size:11px;padding:3px 10px;border-radius:4px;border:1px solid rgba(255,255,255,0.1);background:rgba(91,141,217,0.2);color:rgba(255,255,255,0.7);cursor:pointer;">Easy</button>' +
    '<button class="ai-diff-btn" onclick="window._setAiDiff(this,\'normal\')" data-diff="normal" style="font-size:11px;padding:3px 10px;border-radius:4px;border:1px solid rgba(255,255,255,0.1);background:transparent;color:rgba(255,255,255,0.5);cursor:pointer;">Normal</button>' +
    '<button class="ai-diff-btn" onclick="window._setAiDiff(this,\'hard\')" data-diff="hard" style="font-size:11px;padding:3px 10px;border-radius:4px;border:1px solid rgba(255,255,255,0.1);background:transparent;color:rgba(255,255,255,0.5);cursor:pointer;">Hard</button>' +
    '</div>' +
    '</div>' +

    '<div class="setup-section">' +
    '<div class="setup-label">Starting Life</div>' +
    '<div class="life-total-row">' +
    '<button class="life-adjust-btn" onclick="adjustSetupLife(-5)">-</button>' +
    '<span id="starting-life-display">40</span>' +
    '<button class="life-adjust-btn" onclick="adjustSetupLife(5)">+</button>' +
    '</div>' +
    '</div>' +

    '<div class="setup-section">' +
    '<div class="setup-label">Decks</div>' +
    '<div class="backend-status-row">' +
    '<span id="backend-status-indicator" class="backend-status disconnected">Checking backend...</span>' +
    '</div>' +
    '<div id="deck-assignment-grid" class="deck-assignment-grid"></div>' +
    '</div>' +

    '<button class="btn-start" onclick="startGame()">Begin Battle</button>' +
    '</div>';

  // Init deck assignment grid
  updateDeckAssignmentGrid(4);

  // Expose helpers to window
  // Track AI selections locally
  var _localAiSet = new Set();
  var _localAiDiff = 'easy';

  function _renderAiToggles() {
    var grid = document.getElementById('ai-toggle-grid');
    if (!grid) return;
    grid.innerHTML = '';
    for (var i = 0; i < selectedPlayerCount; i++) {
      (function(idx) {
        var isAi = _localAiSet.has(idx);
        var btn = document.createElement('button');
        btn.style.cssText = 'display:flex;align-items:center;gap:5px;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:12px;' +
          'border:1px solid ' + (isAi ? 'rgba(91,141,217,0.4)' : 'rgba(255,255,255,0.1)') + ';' +
          'background:' + (isAi ? 'rgba(91,141,217,0.15)' : 'transparent') + ';' +
          'color:' + (isAi ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.5)') + ';';
        btn.innerHTML = '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + playerColors[idx].color + ';"></span>' +
          (isAi ? '&#x1F916; AI' : '&#x1F464; Human') + ' <span style="opacity:0.5">P' + (idx + 1) + '</span>';
        btn.setAttribute('onclick', '(function(){})()');
        btn.addEventListener('click', function() {
          if (!_localAiSet.has(idx)) {
            var humanCount = selectedPlayerCount - _localAiSet.size;
            if (humanCount <= 1) return;
            _localAiSet.add(idx);
            var nameInp = document.getElementById('player-name-' + idx);
            if (nameInp && (!nameInp.value.trim() || nameInp.value.startsWith('Player '))) {
              nameInp.value = 'AI Bot ' + (idx + 1);
            }
          } else {
            _localAiSet.delete(idx);
            var nameInp2 = document.getElementById('player-name-' + idx);
            if (nameInp2 && nameInp2.value.startsWith('AI Bot')) nameInp2.value = '';
          }
          _renderAiToggles();
        });
        grid.appendChild(btn);
      })(i);
    }
    var diffRow = document.getElementById('ai-difficulty-row');
    if (diffRow) diffRow.style.display = _localAiSet.size > 0 ? 'flex' : 'none';
  }

  window._setAiDiff = function(el, diff) {
    _localAiDiff = diff;
    document.querySelectorAll('.ai-diff-btn').forEach(function(b) {
      b.style.background = b.getAttribute('data-diff') === diff ? 'rgba(91,141,217,0.2)' : 'transparent';
      b.style.color = b.getAttribute('data-diff') === diff ? 'rgba(255,255,255,0.7)' : 'rgba(255,255,255,0.5)';
      b.classList.toggle('active', b.getAttribute('data-diff') === diff);
    });
  };

  window.selectPlayerCount = function(n) {
    selectedPlayerCount = n;
    document.querySelectorAll('.player-count-btn').forEach((btn, i) => {
      btn.classList.toggle('active', [2, 3, 4][i] === n);
    });
    // Hide/show player fields
    for (let i = 0; i < 4; i++) {
      const field = document.getElementById('player-field-' + i);
      if (field) field.style.display = i < n ? '' : 'none';
    }
    // Clear AI selections for removed players
    _localAiSet.forEach(function(idx) { if (idx >= n) _localAiSet.delete(idx); });
    _renderAiToggles();
    updateDeckAssignmentGrid(n);
  };

  window.adjustSetupLife = function(delta) {
    startingLife = Math.max(10, Math.min(999, startingLife + delta));
    const el = document.getElementById('starting-life-display');
    if (el) el.textContent = startingLife;
  };

  window.startGame = function() {
    const playerNames = [];
    for (let i = 0; i < selectedPlayerCount; i++) {
      const inp = document.getElementById('player-name-' + i);
      playerNames.push(inp ? inp.value.trim() || ((_localAiSet.has(i)) ? 'AI Bot ' + (i + 1) : 'Player ' + (i + 1)) : 'Player ' + (i + 1));
    }
    // Sync AI config to engine globals
    setupAiPlayers = _localAiSet;
    setupAiDifficulty = _localAiDiff;
    initGame(selectedPlayerCount, playerNames, startingLife);
  };

  // Trigger display update for player count
  window.selectPlayerCount(4);
}

function updateDeckAssignmentGrid(playerCount) {
  var grid = document.getElementById('deck-assignment-grid');
  if (!grid) return;
  grid.innerHTML = '';

  var playerColors = [
    { color: '#c0392b', name: 'Crimson' },
    { color: '#2980b9', name: 'Sapphire' },
    { color: '#27ae60', name: 'Emerald' },
    { color: '#d4930d', name: 'Gold' },
  ];

  for (var i = 0; i < playerCount; i++) {
    var isAi = typeof setupAiPlayers !== 'undefined' && setupAiPlayers.has
      ? setupAiPlayers.has(i)
      : (typeof _localAiSet !== 'undefined' && _localAiSet.has(i));

    var nameInput = document.getElementById('player-name-' + i);
    var playerName = (nameInput && nameInput.value.trim()) ||
      (isAi ? ('AI Bot ' + (i + 1)) : ('Player ' + (i + 1)));

    var panel = document.createElement('div');
    panel.className = 'deck-select-panel';
    panel.id = 'deck-panel-' + i;

    if (isAi) {
      panel.innerHTML =
        '<div class="deck-select-panel-header">' +
          '<div class="player-color-dot" style="background:' + playerColors[i].color + '"></div>' +
          '<span class="deck-select-player-name">' + playerName + '</span>' +
          '<span class="deck-select-ai-badge">AI</span>' +
        '</div>' +
        '<div class="deck-select-ai-note">AI Deck (auto-generated)</div>';
    } else {
      panel.innerHTML =
        '<div class="deck-select-panel-header">' +
          '<div class="player-color-dot" style="background:' + playerColors[i].color + '"></div>' +
          '<span class="deck-select-player-name">' + playerName + '</span>' +
          '<span class="deck-select-status" id="deck-status-' + i + '">No deck selected</span>' +
        '</div>' +
        '<div class="deck-tabs" id="deck-tabs-' + i + '">' +
          '<button class="deck-tab active" data-tab="precons" onclick="switchDeckTab(' + i + ',\'precons\')">Precons</button>' +
          '<button class="deck-tab" data-tab="edhrec" onclick="switchDeckTab(' + i + ',\'edhrec\')">EDHREC</button>' +
          '<button class="deck-tab" data-tab="mydecks" onclick="switchDeckTab(' + i + ',\'mydecks\')">My Decks</button>' +
        '</div>' +
        '<div class="deck-tab-content" id="deck-content-' + i + '">' +
          _buildPreconTabContent(i) +
        '</div>';
    }

    grid.appendChild(panel);
  }

  // If backend is connected, load precons from API
  _loadBackendPrecons();
}

function _buildPreconTabContent(playerIdx) {
  var preconList = (typeof PRECON_DATA !== 'undefined') ? PRECON_DATA : [];

  if (preconList.length === 0) {
    return '<div class="deck-tab-empty">No precon data loaded.<br>Connect to Commander-AI-Lab backend for 163+ precons.</div>';
  }

  var html = '<div class="deck-filter-row">' +
    '<input class="deck-filter-input" type="text" placeholder="Filter precons..." ' +
    'oninput="filterPrecons(' + playerIdx + ', this.value)" />' +
    '</div>';

  // Group by set
  var sets = {};
  preconList.forEach(function(p) {
    var setName = p.set || 'Other';
    if (!sets[setName]) sets[setName] = [];
    sets[setName].push(p);
  });

  html += '<div class="deck-precon-list" id="precon-list-' + playerIdx + '">';
  Object.keys(sets).sort().forEach(function(setName) {
    html += '<div class="deck-set-group">';
    html += '<div class="deck-set-header" onclick="toggleDeckSet(this)">';
    html += '<span class="deck-set-arrow">\u25b8</span> ' + setName + ' (' + sets[setName].length + ')';
    html += '</div>';
    html += '<div class="deck-set-items" style="display:none;">';
    sets[setName].forEach(function(p) {
      html += '<button class="deck-precon-item" data-precon-id="' + p.id + '" ' +
        'onclick="selectPreconDeck(' + playerIdx + ',\'' + p.id.replace(/'/g, "\\'") + '\')">';
      html += '<span class="deck-precon-name">' + (p.name || p.id).replace(/</g, '&lt;') + '</span>';
      if (p.commander) {
        html += '<span class="deck-precon-cmdr">' + p.commander.replace(/</g, '&lt;') + '</span>';
      }
      html += '</button>';
    });
    html += '</div></div>';
  });
  html += '</div>';

  return html;
}

async function _loadBackendPrecons() {
  if (typeof AIBridge === 'undefined' || !AIBridge.connector.connected) return;

  try {
    var precons = await AIBridge.deckSource.fetchPrecons();
    if (precons && precons.length > 0) {
      var indicator = document.getElementById('backend-status-indicator');
      if (indicator) {
        indicator.textContent = '\u26a1 ' + precons.length + ' precons from backend';
        indicator.className = 'backend-status connected';
      }
    }
  } catch (e) {
    console.warn('[_loadBackendPrecons] Error:', e);
  }
}

function switchDeckTab(playerIdx, tab) {
  var tabs = document.querySelectorAll('#deck-tabs-' + playerIdx + ' .deck-tab');
  tabs.forEach(function(t) {
    t.classList.toggle('active', t.getAttribute('data-tab') === tab);
  });

  var content = document.getElementById('deck-content-' + playerIdx);
  if (!content) return;

  switch (tab) {
    case 'precons':
      content.innerHTML = _buildPreconTabContent(playerIdx);
      break;

    case 'edhrec':
      content.innerHTML =
        '<div class="deck-edhrec-content">' +
          '<div class="deck-filter-row">' +
            '<input class="deck-filter-input" type="text" placeholder="Search by commander name..." ' +
            'id="edhrec-search-' + playerIdx + '" />' +
            '<button class="btn btn-sm" onclick="searchEdhrec(' + playerIdx + ')">Search</button>' +
          '</div>' +
          '<div id="edhrec-results-' + playerIdx + '" class="deck-edhrec-results">' +
            '<div class="deck-tab-empty">Enter a commander name to find EDHREC recommendations.<br>' +
            '<em style="font-size:10px;opacity:0.6">EDHREC integration coming soon.</em></div>' +
          '</div>' +
        '</div>';
      break;

    case 'mydecks':
      content.innerHTML =
        '<div class="deck-mydecks-content">' +
          '<div class="deck-tab-empty">' +
            '<div style="margin-bottom:8px;">Import a decklist:</div>' +
            '<textarea class="deck-import-textarea" id="deck-import-' + playerIdx + '" ' +
            'placeholder="Paste decklist here...\n1 Sol Ring\n1 Command Tower\n..."></textarea>' +
            '<button class="btn btn-sm" style="margin-top:6px;" ' +
            'onclick="importDeckFromTextarea(' + playerIdx + ')">Import Decklist</button>' +
          '</div>' +
        '</div>';
      break;
  }
}

function filterPrecons(playerIdx, query) {
  var list = document.getElementById('precon-list-' + playerIdx);
  if (!list) return;
  var q = query.toLowerCase().trim();

  list.querySelectorAll('.deck-precon-item').forEach(function(item) {
    var name = item.querySelector('.deck-precon-name');
    var cmdr = item.querySelector('.deck-precon-cmdr');
    var nameText = name ? name.textContent.toLowerCase() : '';
    var cmdrText = cmdr ? cmdr.textContent.toLowerCase() : '';
    var match = !q || nameText.includes(q) || cmdrText.includes(q);
    item.style.display = match ? '' : 'none';
  });

  // Auto-expand groups that have visible items
  list.querySelectorAll('.deck-set-group').forEach(function(group) {
    var items = group.querySelector('.deck-set-items');
    var hasVisible = items && Array.from(items.querySelectorAll('.deck-precon-item'))
      .some(function(it) { return it.style.display !== 'none'; });
    if (items && q) {
      items.style.display = hasVisible ? '' : 'none';
    }
  });
}

function toggleDeckSet(headerEl) {
  var items = headerEl.nextElementSibling;
  if (!items) return;
  var isOpen = items.style.display !== 'none';
  items.style.display = isOpen ? 'none' : '';
  var arrow = headerEl.querySelector('.deck-set-arrow');
  if (arrow) arrow.textContent = isOpen ? '\u25b8' : '\u25be';
}

function selectPreconDeck(playerIdx, preconId) {
  var panel = document.getElementById('deck-panel-' + playerIdx);
  if (panel) {
    panel.querySelectorAll('.deck-precon-item').forEach(function(item) {
      item.classList.remove('selected');
    });
    var selected = panel.querySelector('[data-precon-id="' + preconId + '"]');
    if (selected) selected.classList.add('selected');
  }

  var status = document.getElementById('deck-status-' + playerIdx);
  var preconList = (typeof PRECON_DATA !== 'undefined') ? PRECON_DATA : [];
  var precon = preconList.find(function(p) { return p.id === preconId; });
  if (status) {
    status.textContent = precon ? (precon.name || preconId) + ' selected' : preconId + ' selected';
    status.className = 'deck-select-status selected';
  }

  if (typeof setupDeckChoices === 'undefined') window.setupDeckChoices = {};
  setupDeckChoices[playerIdx] = { type: 'precon', preconId: preconId };
}

function searchEdhrec(playerIdx) {
  var input = document.getElementById('edhrec-search-' + playerIdx);
  var results = document.getElementById('edhrec-results-' + playerIdx);
  if (!input || !results) return;

  var query = input.value.trim();
  if (!query) return;

  results.innerHTML = '<div class="deck-tab-loading">Searching EDHREC for "' + query + '"...</div>';

  if (typeof AIBridge !== 'undefined' && AIBridge.connector.connected) {
    AIBridge.deckSource.fetchEdhrecDecks(query).then(function(decks) {
      if (decks.length === 0) {
        results.innerHTML = '<div class="deck-tab-empty">No results for "' + query + '".<br>' +
          '<em style="font-size:10px;opacity:0.6">EDHREC integration is coming soon.</em></div>';
      } else {
        var html = '';
        decks.forEach(function(d) {
          html += '<button class="deck-precon-item" onclick="selectEdhrecDeck(' + playerIdx + ',\'' + d.name + '\')">' +
            '<span class="deck-precon-name">' + d.name + '</span>' +
            '</button>';
        });
        results.innerHTML = html;
      }
    });
  } else {
    results.innerHTML = '<div class="deck-tab-empty">EDHREC search requires Commander-AI-Lab backend.<br>' +
      '<em style="font-size:10px;opacity:0.6">Start the backend: python lab_api.py</em></div>';
  }
}

function importDeckFromTextarea(playerIdx) {
  var textarea = document.getElementById('deck-import-' + playerIdx);
  if (!textarea) return;
  var text = textarea.value.trim();
  if (!text) return;

  var status = document.getElementById('deck-status-' + playerIdx);
  if (status) {
    status.textContent = 'Decklist imported';
    status.className = 'deck-select-status selected';
  }

  if (typeof setupDeckChoices === 'undefined') window.setupDeckChoices = {};
  setupDeckChoices[playerIdx] = { type: 'import', text: text };
}

// ============================================================
// GAME INITIALIZATION
// ============================================================
function initGame(playerCount, playerNames, startingLife) {
  gameState = createInitialState(playerCount, playerNames, startingLife);
  gameState.inGame = true;

  // Hide setup screen
  const setup = document.getElementById('setup-screen');
  if (setup) setup.classList.add('hidden');

  // Show battlefield
  const bf = document.getElementById('game-battlefield');
  if (bf) bf.style.display = 'block';

  // Update player labels and life counters in the quadrant layout
  for (let i = 0; i < 4; i++) {
    const pNum = i + 1;
    const player = gameState.players[i];
    const area = document.querySelector('.player-area.p' + pNum);

    // Update player label
    const labelEl = area && area.querySelector('.player-label');
    if (labelEl) {
      labelEl.textContent = player ? player.name : '';
      labelEl.style.display = player ? '' : 'none';
    }

    // Show/hide based on player count
    if (area) {
      area.style.display = i < playerCount ? '' : 'none';
    }

    if (player) {
      // Set life counter
      const lifeEl = document.getElementById('life-' + i);
      if (lifeEl) lifeEl.textContent = player.life;
    }
  }

  // Assign precon decks if selected
  for (let i = 0; i < playerCount; i++) {
    const sel = document.getElementById('deck-sel-' + i);
    if (sel && sel.value) {
      const preconList2 = (typeof PRECON_DATA !== 'undefined') ? PRECON_DATA : (typeof PRECONS !== 'undefined') ? PRECONS : [];
      const precon = preconList2.find(p => p.id === sel.value);
      if (precon) loadPreconDeck(i, precon);
    }
  }

  // Mark AI players
  setupAiPlayers.forEach(function(idx) {
    if (gameState.players[idx]) {
      gameState.players[idx].isAI = true;
    }
  });
  gameState.aiDifficulty = setupAiDifficulty;

  // Initialize phase tracker
  renderPhaseTracker();
  updateTurnDisplay();
  renderPlayerPanels();
  renderManaPool(0);

  var aiCount = 0;
  gameState.players.forEach(function(p) { if (p.isAI) aiCount++; });
  addLogEntry('&#x1F3AE; <strong>Game started!</strong> ' + playerCount + ' players, ' + startingLife + ' starting life.' + (aiCount > 0 ? ' (' + aiCount + ' AI on ' + setupAiDifficulty + ')' : ''));
  addLogEntry('<strong>' + gameState.players[0].name + '</strong> begins the game.');

  // Build section areas for each battle zone
  buildQuadrantBattleZones();

  // Show mana pool display
  const manaDisplay = document.getElementById('mana-pool-display');
  if (manaDisplay) manaDisplay.style.display = 'flex';

  // If first player is AI, start their turn after a short delay
  if (gameState.players[0] && gameState.players[0].isAI && typeof runAiTurn === 'function') {
    setTimeout(function() { runAiTurn(); }, 1200);
  }
}

function buildQuadrantBattleZones() {
  // Each player's battle-zone div is already in the HTML
  // Just ensure they have position:relative and overflow:hidden
  for (let i = 0; i < 4; i++) {
    const pNum = i + 1;
    const bz = document.getElementById('battle-zone-' + pNum);
    if (bz) {
      bz.style.position = 'relative';
      bz.style.overflow = 'hidden';
    }
  }
}

function loadPreconDeck(playerIdx, precon) {
  if (!gameState || !precon) return;
  const player = gameState.players[playerIdx];
  if (!player) return;

  player.commanderCardName = precon.commander || '';

  // Parse decklist text if available (PRECON_DATA format)
  const deckText = precon.decklist || '';
  const cards = precon.cards || [];

  // Parse from decklist text
  const lines = deckText.split('\n');
  const parsedCards = [];
  let commanderName = precon.commander || '';
  let inCommanderSection = false;

  lines.forEach(line => {
    line = line.trim();
    if (!line || line.startsWith('//')) {
      inCommanderSection = line.toLowerCase().includes('commander');
      return;
    }
    const match = line.match(/^(\d+)\s+(.+)$/);
    if (match) {
      const qty = parseInt(match[1]);
      const name = match[2].trim();
      if (inCommanderSection || name === commanderName) {
        commanderName = name;
        inCommanderSection = false;
      } else {
        for (let q = 0; q < qty; q++) parsedCards.push(name);
      }
    }
  });

  // Fall back to precon.cards array
  const cardNames = parsedCards.length > 0 ? parsedCards : cards.filter(c => c !== commanderName);

  if (cardNames.length > 0 || commanderName) {
    // Commander to command zone
    if (commanderName) {
      player.zones.command.push({
        name: commanderName,
        imageUrl: '',
        typeLine: 'Legendary Creature',
        oracleText: '',
      });
    }
    // Library
    cardNames.forEach(cardName => {
      player.zones.library.push({
        name: cardName,
        imageUrl: '',
        typeLine: '',
        oracleText: '',
      });
    });
    // Shuffle library
    for (let i = player.zones.library.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [player.zones.library[i], player.zones.library[j]] = [player.zones.library[j], player.zones.library[i]];
    }
    // Draw opening hand (7 cards)
    for (let d = 0; d < 7 && player.zones.library.length > 0; d++) {
      player.zones.hand.push(player.zones.library.shift());
    }
    updateZoneCountsForPlayer(playerIdx);
    renderCommanderZone(playerIdx);
    renderHandZone(playerIdx);
    addLogEntry('<strong>' + player.name + '</strong> loaded deck: <em>' + precon.name + '</em> (' + commanderName + ')');
  }
}

// ============================================================
// SEARCH SIDEBAR
// ============================================================
let searchDebounceTimer = null;

function initSearchSidebar() {
  const input = document.getElementById('card-search-input');
  if (!input) return;

  input.addEventListener('input', () => {
    clearTimeout(searchDebounceTimer);
    const q = input.value.trim();
    if (q.length < 2) {
      setSearchStatus('Type to search cards...');
      document.getElementById('card-results').innerHTML = '';
      return;
    }
    searchDebounceTimer = setTimeout(() => searchCards(q), 300);
  });

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      clearTimeout(searchDebounceTimer);
      const q = input.value.trim();
      if (q.length >= 1) searchCards(q);
    }
  });
}

function setSearchStatus(text) {
  const el = document.getElementById('search-status');
  if (el) el.textContent = text;
}

function showSearchSpinner(show) {
  const el = document.getElementById('card-results');
  if (!el) return;
  if (show) {
    el.innerHTML = '<div class="search-loading"><div class="spinner"></div></div>';
    setSearchStatus('Searching...');
  }
}

function searchCards(query) {
  if (!query) return;
  showSearchSpinner(true);
  const url = 'https://api.scryfall.com/cards/search?q=' + encodeURIComponent(query) + '&unique=cards&order=name&page=1';
  fetch(url)
    .then(r => r.json())
    .then(data => {
      if (data.data) {
        renderSearchResults(data.data.slice(0, 20));
        setSearchStatus(data.total_cards + ' results');
      } else {
        setSearchStatus('No results found');
        document.getElementById('card-results').innerHTML = '<div style="padding:20px;font-size:11px;color:var(--color-text-faint);text-align:center;">No cards found for "' + query + '"</div>';
      }
    })
    .catch(() => {
      setSearchStatus('Search failed');
      document.getElementById('card-results').innerHTML = '<div style="padding:20px;font-size:11px;color:var(--color-error);text-align:center;">Search failed. Check internet connection.</div>';
    });
}

function getCardImage(card) {
  if (card.image_uris) return card.image_uris.normal || card.image_uris.small;
  if (card.card_faces && card.card_faces[0] && card.card_faces[0].image_uris) {
    return card.card_faces[0].image_uris.normal || card.card_faces[0].image_uris.small;
  }
  return '';
}

function renderSearchResults(cards) {
  const container = document.getElementById('card-results');
  if (!container) return;
  container.innerHTML = '';

  cards.forEach(card => {
    const imgUrl = getCardImage(card);
    const item = document.createElement('div');
    item.className = 'search-card-item';
    item.innerHTML =
      (imgUrl ? '<img src="' + imgUrl + '" alt="' + card.name + '" loading="lazy"/>' :
        '<div style="aspect-ratio:63/88;background:rgba(255,255,255,0.05);display:flex;align-items:center;justify-content:center;font-size:10px;color:rgba(255,255,255,0.3);">' + card.name + '</div>') +
      '<div class="search-card-info">' +
        '<div class="search-card-name">' + card.name + '</div>' +
        '<div class="search-card-type">' + (card.type_line || '') + '</div>' +
      '</div>' +
      '<button class="search-card-add-btn" title="Add to battlefield">+</button>';

    // Add to battlefield on click
    const addCard = () => {
      if (!gameState) return;
      const ownerIdx = gameState.currentPlayerIndex;
      addCardToBattlefield(
        card.name, imgUrl, card.type_line || '',
        ownerIdx, undefined, undefined,
        card.oracle_text || card.card_faces?.[0]?.oracle_text || '',
        {
          manaCost: card.mana_cost || '',
          power: card.power || '',
          toughness: card.toughness || '',
          pt: (card.power && card.toughness) ? card.power + '/' + card.toughness : '',
          cmc: card.cmc || 0,
          loyalty: card.loyalty || '',
        }
      );
    };

    item.querySelector('.search-card-add-btn').onclick = e => { e.stopPropagation(); addCard(); };

    item.addEventListener('mouseenter', e => {
      if (imgUrl) showFloatingCardPreview(imgUrl, e, {
        name: card.name,
        typeLine: card.type_line || '',
        oracleText: card.oracle_text || (card.card_faces && card.card_faces[0] ? card.card_faces[0].oracle_text : '') || '',
        manaCost: card.mana_cost || '',
        power: card.power, toughness: card.toughness,
      });
    });
    item.addEventListener('mousemove', positionFloatingPreview);
    item.addEventListener('mouseleave', hideFloatingCardPreview);

    container.appendChild(item);
  });
}

// ============================================================
// TRIGGER BADGE & STACK PANEL
// ============================================================
function updateTriggerBadge() {
  if (!gameState) return;
  const pending = (gameState.triggerStack || []).filter(t => !t.resolved);
  const btn = document.getElementById('btn-triggers');
  if (!btn) return;
  btn.textContent = pending.length > 0 ? '&#x2747; ' + pending.length : '&#x2747;';
  btn.classList.toggle('has-triggers', pending.length > 0);
}

function openTriggerStack() {
  const panel = document.getElementById('trigger-stack-panel');
  if (panel) { panel.classList.add('visible'); renderTriggerStack(); }
}

function closeTriggerStack() {
  const panel = document.getElementById('trigger-stack-panel');
  if (panel) panel.classList.remove('visible');
}

function toggleTriggerStack() {
  const panel = document.getElementById('trigger-stack-panel');
  if (panel) {
    if (panel.classList.contains('visible')) closeTriggerStack();
    else openTriggerStack();
  }
}

function renderTriggerStack() {
  const body = document.getElementById('trigger-stack-body');
  if (!body || !gameState) return;

  const pending = (gameState.triggerStack || []).filter(t => !t.resolved);

  if (pending.length === 0) {
    body.innerHTML = '<div class="trigger-stack-empty">No pending triggers.</div>';
    return;
  }

  body.innerHTML = pending.map((trigger, idx) => {
    const typeIcon = (typeof TRIGGER_TYPE_ICONS !== 'undefined' && TRIGGER_TYPE_ICONS[trigger.type]) || '&#x2747;';
    const typeLabel = (typeof TRIGGER_TYPE_LABELS !== 'undefined' && TRIGGER_TYPE_LABELS[trigger.type]) || trigger.type;
    const ownerColor = (gameState.players[trigger.ownerIndex] || {}).color || '#888';
    return '<div class="trigger-item" data-trigger-id="' + trigger.id + '">' +
      '<div class="trigger-type-icon ' + (trigger.type || '') + '">' + typeIcon + '</div>' +
      '<div class="trigger-item-body">' +
        '<div class="trigger-item-title">' + (trigger.cardName || 'Unknown') + '</div>' +
        '<div class="trigger-item-type">' + typeLabel + '</div>' +
        '<div class="trigger-item-text">' + (trigger.oracleSnippet || '') + '</div>' +
      '</div>' +
      '<div class="trigger-owner-dot" style="background:' + ownerColor + '"></div>' +
      '<button class="trigger-item-dismiss" title="Dismiss" onclick="dismissTrigger(' + trigger.id + ')">&#x2715;</button>' +
      '</div>';
  }).join('');

  updateTriggerBadge();
}

// ============================================================
// UNDO/REDO BUTTONS
// ============================================================
function updateUndoRedoButtons() {
  const undoBtn = document.getElementById('btn-undo');
  const redoBtn = document.getElementById('btn-redo');
  if (undoBtn) undoBtn.disabled = undoStack.length === 0;
  if (redoBtn) redoBtn.disabled = redoStack.length === 0;
  if (undoHistoryVisible) renderUndoHistory();
}

function renderUndoHistory() {
  const panel = document.getElementById('undo-history-panel');
  if (!panel) return;
  // Simple render of last 20 undo states
  const items = undoStack.slice(-20).reverse();
  panel.innerHTML =
    '<div style="padding:10px 14px;border-bottom:1px solid var(--color-border);font-family:var(--font-display);font-size:11px;font-weight:700;color:var(--color-text-muted);text-transform:uppercase;letter-spacing:0.06em;display:flex;justify-content:space-between;">' +
    'Undo History <button onclick="closeUndoHistory()" style="font-size:13px;color:var(--color-text-faint);">&#x2715;</button></div>' +
    '<div style="flex:1;overflow-y:auto;padding:8px;">' +
    items.map((snap, i) => '<div style="padding:5px 8px;font-size:11px;color:var(--color-text-muted);border-bottom:1px solid var(--color-divider);">' +
      (snap._description || 'State #' + (undoStack.length - i)) + '</div>').join('') +
    '</div>';
}

function closeUndoHistory() {
  undoHistoryVisible = false;
  const panel = document.getElementById('undo-history-panel');
  if (panel) panel.classList.remove('visible');
}

// ============================================================
// DICE MODAL
// ============================================================
function openDiceModal() {
  const modal = document.getElementById('dice-modal');
  if (modal) modal.classList.add('visible');
}

function closeDiceModal() {
  const modal = document.getElementById('dice-modal');
  if (modal) modal.classList.remove('visible');
}

function rollDice(sides) {
  const result = Math.floor(Math.random() * sides) + 1;
  const display = document.getElementById('dice-result-display');
  const label = document.getElementById('dice-label');
  if (display) {
    display.textContent = result;
    display.classList.remove('rolling');
    void display.offsetWidth; // Reflow
    display.classList.add('rolling');
  }
  if (label) label.textContent = 'd' + sides + ' Roll';
  addLogEntry('&#x1F3B2; Rolled d' + sides + ': <strong>' + result + '</strong>');
}

function flipCoin() {
  const result = Math.random() < 0.5 ? 'Heads' : 'Tails';
  const display = document.getElementById('dice-result-display');
  const label = document.getElementById('dice-label');
  if (display) { display.textContent = result === 'Heads' ? 'H' : 'T'; display.classList.remove('rolling'); void display.offsetWidth; display.classList.add('rolling'); }
  if (label) label.textContent = 'Coin Flip';
  addLogEntry('&#x1FA99; Coin flip: <strong>' + result + '</strong>');
}

// ============================================================
// TOAST NOTIFICATIONS
// ============================================================
function showToast(message) {
  const toast = document.createElement('div');
  toast.className = 'toast-message';
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.4s';
    setTimeout(() => toast.remove(), 450);
  }, 2800);
}

// ============================================================
// MANA POOL DISPLAY BUTTON
// ============================================================
function showManaPool() {
  const display = document.getElementById('mana-pool-display');
  if (display) {
    display.style.display = display.style.display === 'none' ? 'flex' : 'none';
  }
}

// ============================================================
// SHORTCUT HINT
// ============================================================
let _shortcutHintTimeout = null;

function showShortcutHint() {
  const hint = document.querySelector('.shortcut-hint');
  if (!hint) return;
  const hints = [
    '<kbd>N</kbd> next phase  <kbd>T</kbd> next turn  <kbd>Space</kbd> tap/untap',
    '<kbd>U</kbd> undo  <kbd>D</kbd> draw card  <kbd>S</kbd> search cards',
    '<kbd>G</kbd> dice roll  <kbd>Esc</kbd> close panels',
  ];
  hint.innerHTML = hints[Math.floor(Math.random() * hints.length)];
  hint.classList.add('show');
  clearTimeout(_shortcutHintTimeout);
  _shortcutHintTimeout = setTimeout(() => hint.classList.remove('show'), 4000);
}

// ============================================================
// KEYBOARD SHORTCUTS
// ============================================================
function setupKeyboardShortcuts() {
  document.addEventListener('keydown', e => {
    // Don't fire when typing in inputs
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
    if (!gameState || !gameState.inGame) return;

    switch (e.key.toLowerCase()) {
      case 'n': if (!e.ctrlKey && !e.metaKey) { nextPhase(); e.preventDefault(); } break;
      case 't': if (!e.ctrlKey && !e.metaKey) { nextTurn(); e.preventDefault(); } break;
      case 'u': if (!e.ctrlKey) { undo(); e.preventDefault(); } break;
      case 'y': if (!e.ctrlKey) { redo(); e.preventDefault(); } break;
      case 'd': drawCard(gameState.currentPlayerIndex); break;
      case 's': {
        const sidebar = document.getElementById('card-search-sidebar');
        if (sidebar) {
          sidebar.classList.toggle('collapsed');
          const inp = document.getElementById('card-search-input');
          if (inp && !sidebar.classList.contains('collapsed')) { inp.focus(); }
        }
        break;
      }
      case 'g': openDiceModal(); break;
      case 'escape': {
        hideContextMenu();
        closeZoneModal();
        closeDiceModal();
        if (typeof cancelStackPickMode === 'function') cancelStackPickMode();
        if (typeof cancelEquipPickMode === 'function') cancelEquipPickMode();
        break;
      }
    }

    if (e.ctrlKey && e.key === 'z') { undo(); e.preventDefault(); }
    if (e.ctrlKey && e.key === 'y') { redo(); e.preventDefault(); }
  });
}

// ============================================================
// COMBAT OVERLAY (SVG arrows)
// ============================================================
function refreshCombatOverlay() {
  const svg = document.getElementById('combat-arrows-svg');
  if (!svg || !gameState || !gameState.combat) { return; }

  svg.innerHTML = '';
  const combat = gameState.combat;
  if (!combat.attackers || combat.attackers.length === 0) return;

  // Draw arrows from attacker cards to the target player quadrant
  combat.attackers.forEach(atk => {
    const attackerEl = document.getElementById('bc-' + atk.cardId);
    if (!attackerEl) return;
    const targetPNum = atk.targetPlayerId + 1;
    const targetArea = document.querySelector('.player-area.p' + targetPNum);
    if (!targetArea) return;

    const svgRect = svg.getBoundingClientRect();
    const atkRect = attackerEl.getBoundingClientRect();
    const tgtRect = targetArea.getBoundingClientRect();

    const x1 = atkRect.left + atkRect.width / 2 - svgRect.left;
    const y1 = atkRect.top + atkRect.height / 2 - svgRect.top;
    const x2 = tgtRect.left + tgtRect.width / 2 - svgRect.left;
    const y2 = tgtRect.top + tgtRect.height / 2 - svgRect.top;

    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', x1);
    line.setAttribute('y1', y1);
    line.setAttribute('x2', x2);
    line.setAttribute('y2', y2);
    line.setAttribute('stroke', 'rgba(211,32,42,0.6)');
    line.setAttribute('stroke-width', '2');
    line.setAttribute('stroke-dasharray', '6,3');
    line.setAttribute('marker-end', 'url(#arrowhead)');
    svg.appendChild(line);
  });
}

function updateCombatArrows() { refreshCombatOverlay(); }
function showCombatOverlay() { refreshCombatOverlay(); }

// ============================================================
// SETTINGS PANEL
// ============================================================
function toggleSettingsPanel() {
  const panel = document.getElementById('settings-panel');
  if (panel) panel.classList.toggle('visible');
  if (panel && panel.classList.contains('visible')) renderSettingsPanel();
}

function renderSettingsPanel() {
  if (!gameState) return;
  const body = document.getElementById('settings-body');
  if (!body) return;
  const re = gameState.rulesEngine || {};
  body.innerHTML =
    '<div class="settings-row"><span>Auto Untap</span>' + renderToggle('autoUntap', re.autoUntap) + '</div>' +
    '<div class="settings-row"><span>Auto Draw</span>' + renderToggle('autoDraw', re.autoDraw) + '</div>' +
    '<div class="settings-row"><span>SBA Checks</span>' + renderToggle('sbaChecks', re.sbaChecks) + '</div>' +
    '<div class="settings-row"><span>Commander Tax</span>' + renderToggle('commanderTaxEnabled', re.commanderTaxEnabled) + '</div>' +
    '<div class="settings-row"><span>Auto Resolve Triggers</span>' + renderToggle('autoResolveTriggers', re.autoResolveTriggers) + '</div>' +
    '<div class="settings-row"><span>Enforce Hand Size</span>' + renderToggle('enforceHandSize', re.enforceHandSize) + '</div>' +
    '<div class="settings-row"><span>Auto Eliminate on SBA</span>' + renderToggle('autoEliminateOnSBA', re.autoEliminateOnSBA) + '</div>' +
    '<div class="settings-row"><span>Mana Auto-Clear</span>' + renderToggle('manaAutoClear', gameState.manaAutoClear) + '</div>';
}

function renderToggle(key, value) {
  return '<button class="toggle-switch' + (value ? ' on' : '') + '" onclick="toggleSetting(\'' + key + '\')" title="' + key + '"></button>';
}

function toggleSetting(key) {
  if (!gameState) return;
  if (key === 'manaAutoClear') {
    gameState.manaAutoClear = !gameState.manaAutoClear;
  } else if (gameState.rulesEngine && gameState.rulesEngine[key] !== undefined) {
    gameState.rulesEngine[key] = !gameState.rulesEngine[key];
  }
  renderSettingsPanel();
  addLogEntry('Setting <strong>' + key + '</strong> toggled');
}

// ============================================================
// PLACEHOLDER STUBS for engine-called UI functions
// (engine.js calls these — we provide no-op or simple implementations)
// ============================================================

function renderPlayerPanelsNoOp() { renderPlayerPanels(); }
function showManaShortfallWarning(cardName, shortfall, playerIndex) {
  showToast('Mana shortfall for ' + cardName + ': need ' + shortfall + ' more mana');
}

function closeManaShortfallModal() {}
function renderMulliganUI() {} // Mulligan handled by engine - UI prompt via showToast
function openDeckView(playerId) { openZoneModal(playerId, 'library'); }
function closeDeckView() { closeZoneModal(); }
function renderDeckView() { renderZoneModal(); }
function openFullLogModal() { showToast('Full log: ' + _logEntries.length + ' entries'); }
function closeFullLogModal() {}
function renderFullLog() {}
function renderTimerDisplay() {}
function updateTimerDisplay(playerId) {}
function renderAllTimerDisplays() {}
function flashTimerWarning(playerId) {}
function renderBattlefieldZoneLabels() {}
function renderZonePanel() { updatePlayerZones(); }
function renderZonePanelBody() { renderZoneModal(); }
function showZpContextMenu(x, y, player, zone, cardIndex) { showZoneCardCtx(x, y, player, zone, cardIndex); }
function showHandContextMenu(x, y, playerId, handIndex) {
  // Show context menu for hand card
  if (!gameState) return;
  const player = gameState.players[playerId];
  if (!player || !player.zones.hand[handIndex]) return;
  showZoneCardCtx(x, y, playerId, 'hand', handIndex);
}
function renderDeckStats() {}
function updateDeckSummary(playerId) {}
function updateDeckImportProgress(loaded, total, message) {}
function showPreconDetail(preconId) {}
function closePreconDetail() {}
function showManaPickerModal() {}
function closeManaPickerModal() {}
function updatePlayerNameFields() {}
function updateAiToggleGrid() {}
function renderDeckSelectionGrid() {}
function renderTrainingUI() {}
function openAiTrainingModal() {}
function closeAiTrainingModal() {}
function renderDeckTesterProgress() {}
function renderDeckTesterResults() {}
function openDeckTester() {}
function closeDeckTester() {}
function renderDeckTesterSetup() {}
function updateMonarchBadges() { renderPlayerPanels(); }
function openShortcutsModal() {}
function closeShortcutsModal() {}
function renderShortcutsContent() {}
function openGuideModal() {}
function closeGuideModal() {}
function renderAiThoughtBubble(playerIdx, thought) {}
function showAiCastPopup(card, aiPlayerIdx, handIndex, aiTarget) {}
function closeSaveLoadModal() {}
function renderCollectionGrid() {}
function renderWishlistGrid() {}
function openCollectionAddModal() {}
function closeCollectionAddModal() {}
function renderDbResultGrid(cards) {}
function addCardToDeck(card) {}
function closeDbCtxMenu() {}
function renderDbCommanderSlot() {}
function renderDbList() {}
function updateDbCountDisplay() {}
function renderDbStats() {}
function renderDbCurve() {}
function renderDbColors() {}
function renderDbTypes() {}
function updateCardLegalityDots() {}
function renderDbSavedDecks() {}
function openDeckBuilderImport() {}
function closeDbImportModal() {}
function showImportProgress(current, total, text) {}
function renderSettingsRulesTab() { renderSettingsPanel(); }
function renderSettingsDisplayTab() {}
function renderSettingsGameplayTab() {}
function renderSettingsAITab() {}
function updateDisplaySetting(key, value) {}
function updateGameplaySetting(key, value) { toggleSetting(key); }
function updateAIDifficulty(diff) {}
function updateAISetting(key, value) {}
function renderStackPanel() {}
function updateUnifiedStack() {}
function openPriorityWindow(reason, onAllPass) {}
function closePriorityWindow() {}
function renderPriorityBanner() {}
function showPriorityActionMode() {}
function hidePriorityBanner() {}
function renderLegalActionsBar() {}
function showStackBlockedWarning() {
  addLogEntry('&#x26A0; Resolve all stack items before advancing.');
}
function isPriorityBlocking() { return false; }
function isPriorityEnabled() {
  return gameState && gameState.rulesEngine && gameState.rulesEngine.useStack;
}
function showTargetingWarningBadge(targetCardId, sourceOwnerId) {}
function showColorIdentityWarning(cardName, violations) {
  showToast('Color identity warning: ' + cardName);
}
function showCommanderZonePrompt(cardId, cardData, intendedZone) {
  // Auto-send to command zone
  if (typeof moveCardToZone === 'function') moveCardToZone(cardId, 'command');
}
function showDiscardPrompt(playerId, count) {
  addLogEntry('<strong>' + (gameState.players[playerId] || {}).name + '</strong> must discard ' + count + ' card(s).');
}
function closeDiscardPrompt() {}
function toggleRulesPanel() { toggleSettingsPanel(); }
function closeRulesPanel() { document.getElementById('settings-panel') && document.getElementById('settings-panel').classList.remove('visible'); }
function renderTurnHistory() {}
function updateBattlefieldSectionCounts() {}
function buildBattlefieldSections() {}
function buildOwnerFilterButtons() {}
function applyBattlefieldFilter() {}
function autoArrangeBattlefield() {
  if (!gameState) return;
  gameState.battlefieldCards.forEach((card, idx) => {
    const pNum = card.ownerIndex + 1;
    const bz = document.getElementById('battle-zone-' + pNum);
    if (!bz) return;
    const cols = Math.ceil(Math.sqrt(gameState.battlefieldCards.filter(c => c.ownerIndex === card.ownerIndex).length));
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    card.x = col * 110 + 5;
    card.y = row * 145 + 5;
    const el = document.getElementById('bc-' + card.id);
    if (el) { el.style.left = card.x + 'px'; el.style.top = card.y + 'px'; }
  });
}
function setupBattlefieldDrop() {}
function showDamagePreview() {}
function renderDamagePreviewContent() {}
function showFloatingDamage(elementId, amount, type) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const damage = document.createElement('div');
  damage.className = 'floating-damage';
  damage.textContent = (type === 'loss' ? '-' : '+') + amount;
  damage.style.color = type === 'loss' ? '#e74c3c' : '#2ecc71';
  damage.style.left = (el.offsetLeft + el.offsetWidth / 2) + 'px';
  damage.style.top = (el.offsetTop - 20) + 'px';
  el.parentNode.appendChild(damage);
  setTimeout(() => damage.remove(), 1200);
}
function updateDamageBadge(cardData) {
  const el = document.getElementById('bc-' + cardData.id);
  if (!el) return;
  let badge = el.querySelector('.damage-badge');
  if (cardData.damageMarked > 0) {
    if (!badge) { badge = document.createElement('div'); badge.className = 'damage-badge'; el.appendChild(badge); }
    badge.textContent = cardData.damageMarked;
    badge.style.display = 'flex';
  } else if (badge) {
    badge.style.display = 'none';
  }
}
function showCombatRecap(logLines) {
  if (logLines && logLines.length > 0) {
    logLines.forEach(line => addLogEntry(line));
  }
}
function showPlaneswalkerAbilities(cardId) {}
function closePlaneswalkerAbilities() {}
function openScryModal(playerId, count) { showScryDialog(playerId); }
function closeScryModal() {}
function renderScryZones() {}
function renderScryZone(containerId, cards, zone) {}
function openTokenModal(playerId) {
  const modal = document.getElementById('token-modal');
  if (modal) modal.classList.add('visible');
}
function closeTokenModal() {
  const modal = document.getElementById('token-modal');
  if (modal) modal.classList.remove('visible');
}
function updateTokenPreview() {}
function addToTokenHistory(entry) {}
function renderTokenHistory() {}
function renderTokenBrowserResults(tokens) {}
function updateTokenSummaryBar() {}
function openDeckModal(playerId) {
  const modal = document.getElementById('deck-modal');
  if (modal) {
    modal.classList.add('visible');
    renderDeckModalContent(playerId);
  }
}
function closeDeckModal() {
  const modal = document.getElementById('deck-modal');
  if (modal) modal.classList.remove('visible');
}
function renderDeckModalContent(playerId) {
  const body = document.getElementById('deck-modal-body');
  if (!body || !gameState) return;
  const player = gameState.players[playerId];
  if (!player) return;
  body.innerHTML =
    '<h3 style="font-family:var(--font-display);font-size:14px;color:var(--color-text);margin-bottom:12px;">' + player.name + "'s Deck Manager</h3>" +
    '<div style="margin-bottom:10px;">' +
      '<div style="font-size:11px;color:var(--color-text-muted);margin-bottom:6px;">Commander: <strong>' + (player.commanderCardName || 'Not set') + '</strong></div>' +
      '<div style="font-size:11px;color:var(--color-text-muted);">Library: <strong>' + player.zones.library.length + '</strong> cards | Hand: <strong>' + player.zones.hand.length + '</strong></div>' +
    '</div>' +
    '<div style="margin-bottom:12px;">' +
      '<label style="font-size:11px;font-weight:600;color:var(--color-text);display:block;margin-bottom:5px;">Import Deck (one card per line):</label>' +
      '<textarea id="deck-import-text-' + playerId + '" class="game-textarea" rows="10" placeholder="1 Sol Ring&#10;1 Command Tower&#10;..."></textarea>' +
    '</div>' +
    '<div style="display:flex;gap:8px;">' +
      '<button class="btn btn-primary" onclick="importDeckFromTextarea(' + playerId + ')">&#x1F4E5; Import Deck</button>' +
      '<button class="btn btn-cancel" onclick="closeDeckModal()">Close</button>' +
    '</div>';
}

window.importDeckFromTextarea = function(playerId) {
  const textarea = document.getElementById('deck-import-text-' + playerId);
  if (!textarea || !gameState) return;
  if (typeof importDeckList === 'function') {
    importDeckList(playerId, textarea.value);
  } else {
    showToast('Deck import processing...');
  }
};

function openPreconBrowser() {
  showToast('Precon browser: select a deck from the setup screen dropdown.');
}

// ============================================================
// DOM UTILITY — updateCardCounterBadge
// ============================================================
function updateCardCounterBadge(cardId) {
  if (!gameState) return;
  const card = gameState.battlefieldCards.find(c => c.id === cardId);
  if (!card) return;
  const el = document.getElementById('bc-' + cardId);
  if (!el) return;
  // Re-render counter badges
  const existingStrip = el.querySelector('.card-counters-strip');
  if (existingStrip) existingStrip.remove();

  if (card.counters) {
    const cTypes = Object.keys(card.counters).filter(k => card.counters[k] > 0);
    if (cTypes.length > 0) {
      const strip = document.createElement('div');
      strip.className = 'card-counters-strip';
      cTypes.forEach(cType => {
        const cCount = card.counters[cType];
        const ct = (typeof COUNTER_TYPES !== 'undefined' && COUNTER_TYPES[cType]) || { icon: '\u25CF', color: '#9ca3af', label: cType };
        const badge = document.createElement('span');
        badge.className = 'card-counter-badge';
        badge.style.cssText = 'background:' + ct.color + ';color:#fff;';
        if (cType === '+1/+1') badge.textContent = '+' + cCount + '/+' + cCount;
        else if (cType === '-1/-1') badge.textContent = '-' + cCount + '/-' + cCount;
        else badge.textContent = ct.icon + cCount;
        strip.appendChild(badge);
      });
      el.appendChild(strip);
    }
  }
}

// ============================================================
// DOM — toggleTap visual update
// ============================================================
function _refreshCardEl(cardId) {
  if (!gameState) return;
  const card = gameState.battlefieldCards.find(c => c.id === cardId);
  if (!card) return;
  const el = document.getElementById('bc-' + cardId);
  if (!el) return;
  if (card.tapped) el.classList.add('tapped');
  else el.classList.remove('tapped');
}

// ============================================================
// DOMContentLoaded — wire up everything
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  initSetupScreen();
  initSearchSidebar();
  setupKeyboardShortcuts();

  // Sidebar toggle
  const sidebarTab = document.getElementById('sidebar-edge-tab');
  if (sidebarTab) {
    sidebarTab.onclick = () => {
      const sidebar = document.getElementById('card-search-sidebar');
      if (sidebar) sidebar.classList.toggle('collapsed');
    };
  }

  // Close modal clicks
  document.getElementById('zone-modal') && document.getElementById('zone-modal').addEventListener('click', e => {
    if (e.target.id === 'zone-modal') closeZoneModal();
  });
  document.getElementById('dice-modal') && document.getElementById('dice-modal').addEventListener('click', e => {
    if (e.target.id === 'dice-modal') closeDiceModal();
  });
  document.getElementById('token-modal') && document.getElementById('token-modal').addEventListener('click', e => {
    if (e.target.id === 'token-modal') closeTokenModal();
  });
  document.getElementById('deck-modal') && document.getElementById('deck-modal').addEventListener('click', e => {
    if (e.target.id === 'deck-modal') closeDeckModal();
  });
});
