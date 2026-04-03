// player-panels.js — Enhanced Player Panel Component
// Provides collapsible panels with life, commander damage, counters, and emblems.

'use strict';

/**
 * Create an enhanced player panel widget for a quadrant.
 * Replaces the basic life counter with a full tracking panel.
 *
 * @param {object} player - Player object from gameState
 * @param {number} quadrant - 1-4 (matches CSS class p1-p4)
 * @param {boolean} isActive - Whether this is the active player
 */
function createEnhancedPlayerPanel(player, quadrant, isActive) {
  var panel = document.createElement('div');
  panel.className = 'enhanced-player-panel' +
    (isActive ? ' active-turn' : '') +
    (player.eliminated ? ' eliminated' : '');
  panel.id = 'enhanced-panel-' + player.id;
  panel.setAttribute('data-player-id', player.id);

  // Track collapse state
  var collapseKey = 'panel-collapsed-' + player.id;
  var isCollapsed = localStorage.getItem(collapseKey) === 'true';

  // ── Header Row ──────────────────────────────────────────
  var headerHtml =
    '<div class="epp-header" onclick="togglePlayerPanel(' + player.id + ')">' +
      '<span class="epp-collapse-arrow">' + (isCollapsed ? '\u25b8' : '\u25be') + '</span>' +
      '<div class="epp-name-dot" style="background:' + player.color + '"></div>' +
      '<span class="epp-name">' + player.name + '</span>' +
      (player.isAI ? '<span class="epp-ai-badge">AI</span>' : '') +
      '<span class="epp-life-badge">' +
        '\u2665 ' + player.life +
        (player.life < player.startingLife
          ? ' / ' + player.startingLife
          : '') +
      '</span>' +
    '</div>';

  // ── Life Counter Row ────────────────────────────────────
  var lifeHtml =
    '<div class="epp-life-row">' +
      '<button class="epp-life-btn minus" onclick="adjustLife(' + player.id + ',-1)" ' +
        'oncontextmenu="event.preventDefault();adjustLife(' + player.id + ',-5)" ' +
        'title="Left: -1 | Right: -5">\u2212</button>' +
      '<div class="epp-life-value" id="epp-life-' + player.id + '" ' +
        'onclick="showSetLifeDialog(' + player.id + ')">' +
        player.life +
      '</div>' +
      '<button class="epp-life-btn plus" onclick="adjustLife(' + player.id + ',1)" ' +
        'oncontextmenu="event.preventDefault();adjustLife(' + player.id + ',5)" ' +
        'title="Left: +1 | Right: +5">+</button>' +
    '</div>';

  // ── Commander Damage Section ────────────────────────────
  var otherPlayers = gameState.players.filter(function(p) {
    return p.id !== player.id && !p.eliminated;
  });

  var cmdDmgHtml =
    '<div class="epp-section">' +
      '<div class="epp-section-label">Commander Damage</div>' +
      '<div class="epp-cmd-dmg-grid">';

  otherPlayers.forEach(function(op) {
    var dmg = player.commanderDamage[op.id] || 0;
    var pct = Math.round((dmg / 21) * 100);
    var dangerClass = dmg >= 18 ? 'critical' : dmg >= 10 ? 'warning' : '';

    cmdDmgHtml +=
      '<div class="epp-cmd-dmg-item ' + dangerClass + '">' +
        '<div class="epp-cmd-dmg-bar" style="width:' + pct + '%"></div>' +
        '<div class="epp-cmd-dmg-dot" style="background:' + op.color + '"></div>' +
        '<span class="epp-cmd-dmg-name">' + op.name + '</span>' +
        '<span class="epp-cmd-dmg-value">' + dmg + '/21</span>' +
        '<button class="epp-counter-btn" ' +
          'onclick="event.stopPropagation();adjustCommanderDamage(' + player.id + ',' + op.id + ',1)" ' +
          'title="Add commander damage">+</button>' +
        '<button class="epp-counter-btn" ' +
          'onclick="event.stopPropagation();adjustCommanderDamage(' + player.id + ',' + op.id + ',-1)" ' +
          'title="Remove commander damage">\u2212</button>' +
      '</div>';
  });

  cmdDmgHtml += '</div></div>';

  // ── Counters Section ────────────────────────────────────
  var poison = player.poison || 0;
  var energy = player.energy || 0;
  var experience = player.experience || 0;
  var rad = player.rad || 0;

  var countersHtml =
    '<div class="epp-section">' +
      '<div class="epp-section-label">Counters</div>' +
      '<div class="epp-counters-grid">' +
        _buildCounterWidget('Poison', '\u2620', poison, 10,
          'adjustPoison(' + player.id + ',1)',
          'adjustPoison(' + player.id + ',-1)',
          poison >= 8 ? 'critical' : poison >= 5 ? 'warning' : '') +
        _buildCounterWidget('Energy', '\u269b', energy, 0,
          'adjustEnergy(' + player.id + ',1)',
          'adjustEnergy(' + player.id + ',-1)', '') +
        _buildCounterWidget('Experience', '\u2605', experience, 0,
          'adjustExperience(' + player.id + ',1)',
          'adjustExperience(' + player.id + ',-1)', '') +
        _buildCounterWidget('Rad', '\u2622', rad, 0,
          'adjustRad(' + player.id + ',1)',
          'adjustRad(' + player.id + ',-1)', '') +
      '</div>' +
    '</div>';

  // ── Emblems Section ─────────────────────────────────────
  var emblems = player.emblems || [];
  var emblemsHtml =
    '<div class="epp-section">' +
      '<div class="epp-section-label">Emblems</div>' +
      '<div class="epp-emblems">';

  if (emblems.length === 0) {
    emblemsHtml += '<span class="epp-no-emblems">None</span>';
  } else {
    emblems.forEach(function(emb, idx) {
      emblemsHtml +=
        '<div class="epp-emblem-chip" title="' + emb.name + '">' +
          '<span class="epp-emblem-name">' + emb.name + '</span>' +
          '<button class="epp-emblem-remove" ' +
            'onclick="event.stopPropagation();removeEmblem(' + player.id + ',' + idx + ')">\u00d7</button>' +
        '</div>';
    });
  }

  emblemsHtml +=
      '<button class="epp-add-emblem-btn" ' +
        'onclick="event.stopPropagation();showAddEmblemDialog(' + player.id + ')" ' +
        'title="Add an emblem">+ Emblem</button>' +
      '</div>' +
    '</div>';

  // ── Assemble Panel ──────────────────────────────────────
  var bodyHtml =
    '<div class="epp-body" id="epp-body-' + player.id + '" ' +
      'style="' + (isCollapsed ? 'display:none;' : '') + '">' +
      lifeHtml + cmdDmgHtml + countersHtml + emblemsHtml +
    '</div>';

  panel.innerHTML = headerHtml + bodyHtml;
  return panel;
}

function _buildCounterWidget(label, icon, value, threshold, onInc, onDec, dangerClass) {
  return '<div class="epp-counter ' + dangerClass + '">' +
    '<div class="epp-counter-icon">' + icon + '</div>' +
    '<div class="epp-counter-info">' +
      '<span class="epp-counter-value">' + value + '</span>' +
      '<span class="epp-counter-label">' + label + '</span>' +
    '</div>' +
    '<div class="epp-counter-btns">' +
      '<button class="epp-counter-btn" onclick="event.stopPropagation();' + onInc + '">+</button>' +
      '<button class="epp-counter-btn" onclick="event.stopPropagation();' + onDec + '">\u2212</button>' +
    '</div>' +
  '</div>';
}

function togglePlayerPanel(playerId) {
  var body = document.getElementById('epp-body-' + playerId);
  var panel = document.getElementById('enhanced-panel-' + playerId);
  if (!body || !panel) return;

  var isCollapsed = body.style.display === 'none';
  body.style.display = isCollapsed ? '' : 'none';

  var arrow = panel.querySelector('.epp-collapse-arrow');
  if (arrow) arrow.textContent = isCollapsed ? '\u25be' : '\u25b8';

  localStorage.setItem('panel-collapsed-' + playerId, !isCollapsed);
}

// Counter adjustment functions
function adjustEnergy(playerId, amount) {
  if (!gameState) return;
  var player = gameState.players[playerId];
  if (!player) return;
  player.energy = Math.max(0, (player.energy || 0) + amount);
  addLogEntry('<strong>' + player.name + '</strong> energy: ' + player.energy);
  renderEnhancedPanels();
}

function adjustExperience(playerId, amount) {
  if (!gameState) return;
  var player = gameState.players[playerId];
  if (!player) return;
  player.experience = Math.max(0, (player.experience || 0) + amount);
  addLogEntry('<strong>' + player.name + '</strong> experience: ' + player.experience);
  renderEnhancedPanels();
}

function adjustRad(playerId, amount) {
  if (!gameState) return;
  var player = gameState.players[playerId];
  if (!player) return;
  player.rad = Math.max(0, (player.rad || 0) + amount);
  addLogEntry('<strong>' + player.name + '</strong> rad counters: ' + player.rad);
  renderEnhancedPanels();
}

function showAddEmblemDialog(playerId) {
  var name = prompt('Enter emblem name (e.g., "Sorin, Vengeful Bloodlord"):');
  if (!name || !name.trim()) return;
  if (!gameState) return;
  var player = gameState.players[playerId];
  if (!player) return;
  if (!player.emblems) player.emblems = [];
  player.emblems.push({ name: name.trim() });
  addLogEntry('<strong>' + player.name + '</strong> gained emblem: ' + name.trim());
  renderEnhancedPanels();
}

function removeEmblem(playerId, idx) {
  if (!gameState) return;
  var player = gameState.players[playerId];
  if (!player || !player.emblems) return;
  var removed = player.emblems.splice(idx, 1);
  if (removed.length > 0) {
    addLogEntry('<strong>' + player.name + '</strong> lost emblem: ' + removed[0].name);
  }
  renderEnhancedPanels();
}

/**
 * Re-render all enhanced player panels in their quadrant positions.
 */
function renderEnhancedPanels() {
  if (!gameState) return;

  for (var i = 0; i < gameState.players.length; i++) {
    var player = gameState.players[i];
    var quadrant = i + 1;
    var areaEl = document.getElementById('player-area-' + quadrant);
    if (!areaEl) continue;

    // Find or create the enhanced panel container
    var container = areaEl.querySelector('.epp-container');
    if (!container) {
      container = document.createElement('div');
      container.className = 'epp-container';
      // Insert before the zone row
      var zoneRow = areaEl.querySelector('.zone-row');
      if (zoneRow) {
        areaEl.insertBefore(container, zoneRow);
      } else {
        areaEl.appendChild(container);
      }
    }

    var isActive = gameState.currentPlayerIndex === i;
    var panel = createEnhancedPlayerPanel(player, quadrant, isActive);
    container.innerHTML = '';
    container.appendChild(panel);

    // Hide the old life counter (we have our own now)
    var oldLifeCounter = areaEl.querySelector('.life-counter');
    if (oldLifeCounter) oldLifeCounter.style.display = 'none';

    // Hide old poison badge (we have counters section)
    var oldPoison = areaEl.querySelector('.poison-badge');
    if (oldPoison) oldPoison.style.display = 'none';
  }
}
