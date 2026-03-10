/**
 * Commander AI Lab — Web UI Controller v3
 * ═══════════════════════════════════════
 *
 * v3 adds:
 *   - URL import (Archidekt/EDHREC) — paste a URL to import a deck
 *   - Commander meta picker — browse/search 15 built-in commanders, one-click EDHREC fetch
 *   - Text import modal — paste a card list directly
 *   - Source badges on result cards — shows where each deck came from
 *   - Imported deck info in deck selectors
 *
 * Endpoints consumed:
 *   GET  /api/lab/decks              — List available Commander decks
 *   POST /api/lab/start              — Start a batch run
 *   GET  /api/lab/status             — Poll progress
 *   GET  /api/lab/result             — Get completed results JSON
 *   GET  /api/lab/log                — Get live log output
 *   GET  /api/lab/history            — List past batch runs
 *   POST /api/lab/import/url         — Import deck from Archidekt/EDHREC URL
 *   POST /api/lab/import/text        — Import deck from card list text
 *   GET  /api/lab/meta/commanders    — List available commanders in meta mapping
 *   GET  /api/lab/meta/search        — Search commanders by name
 *   POST /api/lab/meta/fetch         — Fetch EDHREC average deck for a commander
 */

const AiLab = (() => {
    'use strict';

    // ── State ──────────────────────────────────────────────
    let isRunning = false;
    let selectedDecks = [null, null, null];
    let lastResult = null;
    let pollInterval = null;
    let logInterval = null;
    let backendAvailable = false;
    let availableDecks = [];
    let metaCommanders = [];
    let preconDecks = [];       // Loaded from /api/lab/precons
    let importedDeckMeta = {};  // deckName → {source, sourceUrl, commander, archetype, colorIdentity}

    // ── Configuration ──────────────────────────────────────
    const API_BASE = window.location.origin;
    const PRESET_GAMES = [10, 100, 1000];
    const POLL_RATE_MS = 750;
    const LOG_RATE_MS = 1000;

    const COLOR_MAP = {
        W: { label: 'W', bg: '#f9faf4', color: '#3d3929' },
        U: { label: 'U', bg: '#0e67ab', color: '#fff' },
        B: { label: 'B', bg: '#2b2424', color: '#ccc' },
        R: { label: 'R', bg: '#d3202a', color: '#fff' },
        G: { label: 'G', bg: '#00733e', color: '#fff' },
    };

    // ── Initialization ─────────────────────────────────────

    async function init() {
        renderPanel();
        await detectBackend();
        await Promise.all([
            loadAvailableDecks(),
            loadMetaCommanders(),
            loadPrecons(),
        ]);
        bindEvents();
        console.log('[AI Lab] v3 Initialized — backend:', backendAvailable ? 'connected' : 'demo mode');
    }

    async function detectBackend() {
        try {
            const res = await fetch(`${API_BASE}/api/lab/decks`, { signal: AbortSignal.timeout(3000) });
            backendAvailable = res.ok;
        } catch {
            backendAvailable = false;
        }
        updateBackendIndicator();
    }

    // ── Render ─────────────────────────────────────────────

    function renderPanel() {
        const container = document.getElementById('ai-lab-container');
        if (!container) return;

        container.innerHTML = `
        <div id="ai-lab-panel">
            <div class="lab-header">
                <h2>Commander AI Lab</h2>
                <div class="lab-backend-status" id="lab-backend-status">
                    <span class="status-dot"></span>
                    <span class="status-text">Checking...</span>
                </div>
            </div>
            <p class="lab-subtitle">Headless 3-AI batch simulation — stress-test your decks at scale</p>

            <!-- v3: Import Bar -->
            <div class="lab-import-bar">
                <div class="lab-import-bar-label">Import Deck</div>
                <div class="lab-import-actions">
                    <button class="lab-import-action-btn" onclick="AiLab.showUrlImport()" title="Import from Archidekt or EDHREC URL">
                        <span class="import-icon">🔗</span> URL Import
                    </button>
                    <button class="lab-import-action-btn" onclick="AiLab.showMetaPicker()" title="Browse EDHREC average decks for popular commanders">
                        <span class="import-icon">📊</span> Commander Meta
                    </button>
                    <button class="lab-import-action-btn" onclick="AiLab.showTextImport()" title="Paste a card list directly">
                        <span class="import-icon">📋</span> Text Import
                    </button>
                    <button class="lab-import-action-btn lab-precon-btn" onclick="AiLab.showPreconPicker()" title="Browse and load official Commander precon decks">
                        <span class="import-icon">🎴</span> Precon Decks
                    </button>
                </div>
            </div>

            <!-- v3: URL Import Panel (hidden by default) -->
            <div class="lab-url-import" id="lab-url-import">
                <div class="lab-url-import-header">
                    <span>Import from URL</span>
                    <button class="lab-panel-close" onclick="AiLab.hideUrlImport()">✕</button>
                </div>
                <div class="lab-url-import-body">
                    <input type="text" id="lab-import-url-input"
                           placeholder="Paste Archidekt or EDHREC URL (e.g. https://archidekt.com/decks/12345)"
                           autocomplete="off" />
                    <button class="lab-url-import-btn" id="lab-url-import-btn" onclick="AiLab.importFromUrl()">
                        Import
                    </button>
                </div>
                <div class="lab-import-hint">
                    Supported: <strong>archidekt.com/decks/...</strong> · <strong>edhrec.com/average-decks/...</strong> · <strong>edhrec.com/commanders/...</strong>
                </div>
                <div class="lab-import-status" id="lab-url-import-status"></div>
            </div>

            <!-- Deck Selection -->
            <div class="lab-deck-grid">
                ${[0, 1, 2].map(i => `
                <div class="lab-deck-slot" id="lab-slot-${i}" data-seat="${i}">
                    <div class="seat-label">Seat ${i + 1}</div>
                    <select id="lab-deck-select-${i}" onchange="AiLab.selectDeck(${i}, this.value)">
                        <option value="">— Select Deck —</option>
                    </select>
                    <div class="commander-name" id="lab-commander-${i}"></div>
                    <div class="lab-deck-source-badge" id="lab-source-badge-${i}"></div>
                </div>
                `).join('')}
            </div>

            <!-- Controls -->
            <div class="lab-controls">
                <div class="lab-control-group">
                    <label>Games:</label>
                    <input type="number" id="lab-game-count" value="100" min="1" max="10000" />
                    <div class="lab-preset-btns">
                        ${PRESET_GAMES.map(n => `
                        <button class="lab-preset-btn ${n === 100 ? 'active' : ''}"
                                onclick="AiLab.setGameCount(${n})">${n}</button>
                        `).join('')}
                    </div>
                </div>
                <div class="lab-control-group">
                    <label>Threads:</label>
                    <select id="lab-threads">
                        <option value="1">1</option>
                        <option value="2">2</option>
                        <option value="4" selected>4</option>
                        <option value="8">8</option>
                    </select>
                </div>
                <div class="lab-control-group">
                    <label>Seed:</label>
                    <input type="text" id="lab-seed" placeholder="Random" style="width:100px" />
                </div>
                <button class="lab-run-btn" id="lab-run-btn" onclick="AiLab.startBatch()">
                    <span class="run-icon">▶</span>
                    <span class="spinner"></span>
                    <span class="run-text">Run AI Sims</span>
                </button>
            </div>

            <!-- Progress -->
            <div class="lab-progress" id="lab-progress">
                <div class="lab-progress-bar">
                    <div class="lab-progress-fill" id="lab-progress-fill"></div>
                </div>
                <div class="lab-progress-text">
                    <span id="lab-progress-count">0 / 0 games</span>
                    <span id="lab-progress-eta"></span>
                </div>
            </div>

            <!-- Live Log -->
            <div class="lab-log" id="lab-log">
                <div class="lab-log-header">
                    <span>Live Output</span>
                    <button class="lab-log-toggle" id="lab-log-toggle" onclick="AiLab.toggleLog()">▼</button>
                </div>
                <pre class="lab-log-content" id="lab-log-content"></pre>
            </div>

            <!-- Results -->
            <div class="lab-results" id="lab-results">
                <div class="lab-results-header">
                    <h3>Results</h3>
                    <div class="lab-results-actions">
                        <button class="lab-export-btn" onclick="AiLab.exportJson()">Export JSON</button>
                        <button class="lab-history-btn" onclick="AiLab.showHistory()">History</button>
                    </div>
                </div>
                <div class="lab-stats-cards" id="lab-stats-cards"></div>
                <div class="lab-global-stats" id="lab-global-stats"></div>

                <!-- Enhanced Results Sections -->
                <div class="lab-section-divider"></div>

                <!-- Tab Navigation -->
                <div class="lab-results-tabs" id="lab-results-tabs">
                    <button class="lab-tab active" data-tab="tab-charts" onclick="AiLab.switchTab('tab-charts')">Charts</button>
                    <button class="lab-tab" data-tab="tab-h2h" onclick="AiLab.switchTab('tab-h2h')">Head-to-Head</button>
                    <button class="lab-tab" data-tab="tab-combat" onclick="AiLab.switchTab('tab-combat')">Combat Stats</button>
                    <button class="lab-tab" data-tab="tab-gamelog" onclick="AiLab.switchTab('tab-gamelog')">Game Log</button>
                </div>

                <!-- Tab: Charts -->
                <div class="lab-tab-panel active" id="tab-charts">
                    <div class="lab-charts-grid">
                        <div class="lab-chart-box">
                            <h4>Win Rate Comparison</h4>
                            <canvas id="lab-chart-winrate" width="400" height="250"></canvas>
                        </div>
                        <div class="lab-chart-box">
                            <h4>Win Conditions</h4>
                            <canvas id="lab-chart-wincond" width="400" height="250"></canvas>
                        </div>
                        <div class="lab-chart-box">
                            <h4>Turn Distribution</h4>
                            <canvas id="lab-chart-turns" width="400" height="250"></canvas>
                        </div>
                        <div class="lab-chart-box">
                            <h4>Win Rate Over Time</h4>
                            <canvas id="lab-chart-wintrend" width="400" height="250"></canvas>
                        </div>
                    </div>
                </div>

                <!-- Tab: Head-to-Head -->
                <div class="lab-tab-panel" id="tab-h2h">
                    <div id="lab-h2h-matrix"></div>
                </div>

                <!-- Tab: Combat Stats -->
                <div class="lab-tab-panel" id="tab-combat">
                    <div id="lab-combat-stats"></div>
                </div>

                <!-- Tab: Game Log -->
                <div class="lab-tab-panel" id="tab-gamelog">
                    <div class="lab-gamelog-controls">
                        <input type="text" id="lab-gamelog-filter" placeholder="Filter by deck name, win condition..." class="lab-gamelog-search">
                        <span class="lab-gamelog-count" id="lab-gamelog-count"></span>
                    </div>
                    <div class="lab-gamelog-wrapper" id="lab-gamelog-wrapper"></div>
                </div>
            </div>

            <!-- History Modal -->
            <div class="lab-modal-overlay" id="lab-history-modal">
                <div class="lab-modal-content">
                    <div class="lab-modal-header">
                        <h3>Batch History</h3>
                        <button class="lab-modal-close" onclick="AiLab.closeHistory()">✕</button>
                    </div>
                    <div class="lab-history-list" id="lab-history-list">Loading...</div>
                </div>
            </div>

            <!-- v3: Commander Meta Picker Modal -->
            <div class="lab-modal-overlay" id="lab-meta-modal">
                <div class="lab-modal-content lab-modal-wide">
                    <div class="lab-modal-header">
                        <h3>Commander Meta — EDHREC Average Decks</h3>
                        <button class="lab-modal-close" onclick="AiLab.closeMetaPicker()">✕</button>
                    </div>
                    <div class="lab-meta-search-row">
                        <input type="text" id="lab-meta-search" placeholder="Search commanders..."
                               oninput="AiLab.filterMetaCommanders(this.value)" autocomplete="off" />
                    </div>
                    <div class="lab-meta-list" id="lab-meta-list">Loading...</div>
                    <div class="lab-import-status" id="lab-meta-import-status"></div>
                </div>
            </div>

            <!-- v3: Precon Picker Modal -->
            <div class="lab-modal-overlay" id="lab-precon-modal">
                <div class="lab-modal-content lab-modal-wide">
                    <div class="lab-modal-header">
                        <h3>Precon Decks — Official Commander Precons</h3>
                        <button class="lab-modal-close" onclick="AiLab.closePreconPicker()">✕</button>
                    </div>
                    <div class="lab-precon-controls">
                        <input type="text" id="lab-precon-search" placeholder="Search precons..."
                               oninput="AiLab.filterPrecons(this.value)" autocomplete="off" />
                        <button class="lab-precon-install-all-btn" onclick="AiLab.installAllPrecons()"
                                title="Install all precon decks to Forge">
                            Install All
                        </button>
                    </div>
                    <div class="lab-precon-grid" id="lab-precon-grid">Loading...</div>
                    <div class="lab-import-status" id="lab-precon-status"></div>
                </div>
            </div>

            <!-- v3: Text Import Modal -->
            <div class="lab-modal-overlay" id="lab-text-modal">
                <div class="lab-modal-content lab-modal-wide">
                    <div class="lab-modal-header">
                        <h3>Import from Card List</h3>
                        <button class="lab-modal-close" onclick="AiLab.closeTextImport()">✕</button>
                    </div>
                    <div class="lab-text-import-body">
                        <div class="lab-text-import-hint">
                            Paste a card list (one card per line). Use <code>1 Card Name</code> or just <code>Card Name</code>.
                            Add a <code>[Commander]</code> section header above the commander, or enter it below.
                        </div>
                        <textarea id="lab-text-import-area" rows="12"
                            placeholder="[Commander]
1 Edgar Markov

[Main]
1 Sol Ring
1 Arcane Signet
1 Command Tower
..."></textarea>
                        <div class="lab-text-import-options">
                            <label>Commander override:</label>
                            <input type="text" id="lab-text-commander-override" placeholder="(auto-detect from list)" />
                        </div>
                        <button class="lab-import-submit-btn" onclick="AiLab.importFromText()">
                            Import Deck
                        </button>
                    </div>
                    <div class="lab-import-status" id="lab-text-import-status"></div>
                </div>
            </div>
        </div>
        `;
    }

    function updateBackendIndicator() {
        const el = document.getElementById('lab-backend-status');
        if (!el) return;
        if (backendAvailable) {
            el.classList.add('connected');
            el.classList.remove('disconnected');
            el.querySelector('.status-text').textContent = 'Backend Connected';
        } else {
            el.classList.add('disconnected');
            el.classList.remove('connected');
            el.querySelector('.status-text').textContent = 'Demo Mode';
        }
    }

    // ── Deck Management ────────────────────────────────────

    async function loadAvailableDecks() {
        let decks = [];

        if (backendAvailable) {
            try {
                const res = await fetch(`${API_BASE}/api/lab/decks`);
                if (res.ok) {
                    const data = await res.json();
                    decks = (data.decks || []).map(d => ({
                        name: d.name,
                        commander: d.commander || d.name.replace(/_/g, ' '),
                    }));
                }
            } catch (err) {
                console.warn('[AI Lab] Failed to load decks from backend:', err);
            }
        }

        // Fallback to sample decks if backend returned nothing
        if (decks.length === 0) {
            decks = getSampleDecks();
        }

        availableDecks = decks;
        refreshDeckSelectors();
    }

    function refreshDeckSelectors() {
        for (let seat = 0; seat < 3; seat++) {
            const select = document.getElementById(`lab-deck-select-${seat}`);
            if (!select) continue;
            const prev = select.value;
            select.innerHTML = '<option value="">— Select Deck —</option>';

            // Group: imported decks first
            const imported = availableDecks.filter(d => importedDeckMeta[d.name]);
            const local = availableDecks.filter(d => !importedDeckMeta[d.name]);

            if (imported.length > 0) {
                const group = document.createElement('optgroup');
                group.label = 'Imported Decks';
                imported.forEach(deck => {
                    const opt = document.createElement('option');
                    opt.value = deck.name;
                    const meta = importedDeckMeta[deck.name];
                    const srcTag = meta ? ` [${meta.source}]` : '';
                    opt.textContent = deck.name + srcTag;
                    opt.dataset.commander = deck.commander || '';
                    group.appendChild(opt);
                });
                select.appendChild(group);
            }

            if (local.length > 0) {
                const group = document.createElement('optgroup');
                group.label = 'Local Decks';
                local.forEach(deck => {
                    const opt = document.createElement('option');
                    opt.value = deck.name;
                    opt.textContent = deck.name;
                    opt.dataset.commander = deck.commander || '';
                    group.appendChild(opt);
                });
                select.appendChild(group);
            }

            // Restore previous selection
            if (prev) {
                select.value = prev;
            }
        }
    }

    function getSampleDecks() {
        return [
            { name: 'Atraxa_Superfriends', commander: "Atraxa, Praetors' Voice" },
            { name: 'Korvold_Aristocrats', commander: 'Korvold, Fae-Cursed King' },
            { name: 'Muldrotha_Value', commander: 'Muldrotha, the Gravetide' },
            { name: 'Angels', commander: 'Angels' },
            { name: 'Edgar Markov', commander: 'Edgar Markov' },
            { name: 'Grimgrin', commander: 'Grimgrin, Corpse-Born' },
            { name: 'Xyris', commander: 'Xyris, the Writhing Storm' },
            { name: 'Control-Talrand', commander: 'Talrand, Sky Summoner' },
            { name: 'Ashling 2.0', commander: 'Ashling the Pilgrim' },
        ];
    }

    function selectDeck(seat, deckName) {
        selectedDecks[seat] = deckName || null;

        const slot = document.getElementById(`lab-slot-${seat}`);
        const cmdEl = document.getElementById(`lab-commander-${seat}`);
        const select = document.getElementById(`lab-deck-select-${seat}`);
        const badgeEl = document.getElementById(`lab-source-badge-${seat}`);

        if (deckName) {
            slot.classList.add('filled');
            const opt = select.selectedOptions[0];
            cmdEl.textContent = opt?.dataset.commander || '';

            // Show source badge if imported
            const meta = importedDeckMeta[deckName];
            if (meta && badgeEl) {
                badgeEl.innerHTML = renderSourceBadge(meta.source, meta.sourceUrl);
                badgeEl.style.display = 'block';
            } else if (badgeEl) {
                badgeEl.innerHTML = '';
                badgeEl.style.display = 'none';
            }
        } else {
            slot.classList.remove('filled');
            cmdEl.textContent = '';
            if (badgeEl) {
                badgeEl.innerHTML = '';
                badgeEl.style.display = 'none';
            }
        }
    }

    function renderSourceBadge(source, sourceUrl) {
        const sourceLabels = {
            'Archidekt': { icon: '🏗️', cls: 'badge-archidekt' },
            'EDHREC Average': { icon: '📊', cls: 'badge-edhrec' },
            'Text Import': { icon: '📋', cls: 'badge-text' },
            'Precon': { icon: '🎴', cls: 'badge-precon' },
        };
        const info = sourceLabels[source] || { icon: '📦', cls: 'badge-default' };
        const linkHtml = sourceUrl
            ? `<a href="${sourceUrl}" target="_blank" rel="noopener" class="source-link">${source}</a>`
            : `<span>${source}</span>`;
        return `<span class="lab-source-badge ${info.cls}">${info.icon} ${linkHtml}</span>`;
    }

    // ── v3: URL Import ────────────────────────────────────

    function showUrlImport() {
        const panel = document.getElementById('lab-url-import');
        if (panel) {
            panel.classList.toggle('active');
            if (panel.classList.contains('active')) {
                document.getElementById('lab-import-url-input')?.focus();
            }
        }
    }

    function hideUrlImport() {
        const panel = document.getElementById('lab-url-import');
        if (panel) panel.classList.remove('active');
    }

    async function importFromUrl() {
        const input = document.getElementById('lab-import-url-input');
        const statusEl = document.getElementById('lab-url-import-status');
        const btn = document.getElementById('lab-url-import-btn');
        const url = input?.value.trim();

        if (!url) {
            showImportStatus(statusEl, 'Please enter a URL.', 'error');
            return;
        }

        if (!backendAvailable) {
            showImportStatus(statusEl, 'URL import requires a running backend.', 'error');
            return;
        }

        btn.disabled = true;
        btn.textContent = 'Importing...';
        showImportStatus(statusEl, 'Fetching deck from URL...', 'loading');

        try {
            const res = await fetch(`${API_BASE}/api/lab/import/url`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url }),
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Import failed');
            }

            // Track imported deck metadata
            importedDeckMeta[data.dckFile] = {
                source: data.source,
                sourceUrl: data.sourceUrl,
                commander: data.commander,
                archetype: data.archetype,
                colorIdentity: data.colorIdentity || [],
            };

            // Add to available decks if not already present
            if (!availableDecks.find(d => d.name === data.dckFile)) {
                availableDecks.unshift({
                    name: data.dckFile,
                    commander: data.commander,
                });
                refreshDeckSelectors();
            }

            showImportStatus(statusEl,
                `Imported "${data.deckName}" (${data.totalCards} cards) from ${data.source}`,
                'success'
            );
            input.value = '';

        } catch (err) {
            showImportStatus(statusEl, `Error: ${err.message}`, 'error');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Import';
        }
    }

    // ── v3: Commander Meta Picker ─────────────────────────

    async function loadMetaCommanders() {
        if (!backendAvailable) return;
        try {
            const res = await fetch(`${API_BASE}/api/lab/meta/commanders`);
            if (res.ok) {
                const data = await res.json();
                metaCommanders = data.commanders || [];
            }
        } catch (err) {
            console.warn('[AI Lab] Failed to load meta commanders:', err);
        }
    }

    function showMetaPicker() {
        const modal = document.getElementById('lab-meta-modal');
        if (modal) {
            modal.classList.add('active');
            renderMetaList(metaCommanders);
            document.getElementById('lab-meta-search')?.focus();
        }
    }

    function closeMetaPicker() {
        const modal = document.getElementById('lab-meta-modal');
        if (modal) modal.classList.remove('active');
        const statusEl = document.getElementById('lab-meta-import-status');
        if (statusEl) statusEl.innerHTML = '';
    }

    function filterMetaCommanders(query) {
        if (!query) {
            renderMetaList(metaCommanders);
            return;
        }
        const q = query.toLowerCase();
        const filtered = metaCommanders.filter(c => c.name.toLowerCase().includes(q));
        renderMetaList(filtered);
    }

    function renderMetaList(commanders) {
        const listEl = document.getElementById('lab-meta-list');
        if (!listEl) return;

        if (commanders.length === 0) {
            listEl.innerHTML = '<div class="lab-meta-empty">No commanders found.</div>';
            return;
        }

        listEl.innerHTML = commanders.map(c => {
            const colors = (c.colorIdentity || []).map(col => {
                const ci = COLOR_MAP[col];
                return ci ? `<span class="mana-pip" style="background:${ci.bg};color:${ci.color}">${ci.label}</span>` : '';
            }).join('');

            const archBadge = c.archetype
                ? `<span class="lab-arch-badge arch-${c.archetype}">${c.archetype}</span>`
                : '';

            return `
            <div class="lab-meta-card" onclick="AiLab.fetchMetaDeck('${escapeAttr(c.name)}')">
                <div class="meta-card-left">
                    <div class="meta-card-name">${escapeHtml(c.name)}</div>
                    <div class="meta-card-info">${colors} ${archBadge}</div>
                </div>
                <div class="meta-card-right">
                    <button class="lab-meta-fetch-btn" title="Fetch EDHREC average deck">
                        Fetch Deck
                    </button>
                </div>
            </div>`;
        }).join('');
    }

    async function fetchMetaDeck(commanderName) {
        const statusEl = document.getElementById('lab-meta-import-status');

        if (!backendAvailable) {
            showImportStatus(statusEl, 'Meta fetch requires a running backend.', 'error');
            return;
        }

        showImportStatus(statusEl, `Fetching EDHREC average deck for ${commanderName}...`, 'loading');

        try {
            const res = await fetch(`${API_BASE}/api/lab/meta/fetch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ commander: commanderName }),
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Fetch failed');
            }

            importedDeckMeta[data.dckFile] = {
                source: 'EDHREC Average',
                sourceUrl: data.sourceUrl,
                commander: data.commander,
                colorIdentity: data.colorIdentity || [],
                sampleSize: data.sampleSize,
            };

            if (!availableDecks.find(d => d.name === data.dckFile)) {
                availableDecks.unshift({
                    name: data.dckFile,
                    commander: data.commander,
                });
                refreshDeckSelectors();
            }

            const sampleInfo = data.sampleSize ? ` (${data.sampleSize} decks sampled)` : '';
            showImportStatus(statusEl,
                `Imported "${data.deckName}" (${data.totalCards} cards)${sampleInfo}`,
                'success'
            );

        } catch (err) {
            showImportStatus(statusEl, `Error: ${err.message}`, 'error');
        }
    }

    // ── v3: Precon Decks ──────────────────────────────────

    async function loadPrecons() {
        if (!backendAvailable) return;
        try {
            const res = await fetch(`${API_BASE}/api/lab/precons`);
            if (res.ok) {
                const data = await res.json();
                preconDecks = data.precons || [];
            }
        } catch (err) {
            console.warn('[AI Lab] Failed to load precons:', err);
        }
    }

    function showPreconPicker() {
        const modal = document.getElementById('lab-precon-modal');
        if (modal) {
            modal.classList.add('active');
            renderPreconGrid(preconDecks);
            document.getElementById('lab-precon-search')?.focus();
        }
    }

    function closePreconPicker() {
        const modal = document.getElementById('lab-precon-modal');
        if (modal) modal.classList.remove('active');
        const statusEl = document.getElementById('lab-precon-status');
        if (statusEl) statusEl.innerHTML = '';
    }

    function filterPrecons(query) {
        if (!query) {
            renderPreconGrid(preconDecks);
            return;
        }
        const q = query.toLowerCase();
        const filtered = preconDecks.filter(p =>
            p.name.toLowerCase().includes(q) ||
            p.commander.toLowerCase().includes(q) ||
            p.set.toLowerCase().includes(q) ||
            (p.theme && p.theme.toLowerCase().includes(q))
        );
        renderPreconGrid(filtered);
    }

    function renderPreconGrid(precons) {
        const gridEl = document.getElementById('lab-precon-grid');
        if (!gridEl) return;

        if (precons.length === 0) {
            gridEl.innerHTML = '<div class="lab-meta-empty">No precon decks found.</div>';
            return;
        }

        gridEl.innerHTML = precons.map(p => {
            const colors = (p.colors || []).map(col => {
                if (col === 'C') return '<span class="mana-pip" style="background:#9c8e82;color:#fff">C</span>';
                const ci = COLOR_MAP[col];
                return ci ? `<span class="mana-pip" style="background:${ci.bg};color:${ci.color}">${ci.label}</span>` : '';
            }).join('');

            const isInstalled = availableDecks.some(d =>
                d.name === p.fileName.replace('.dck', '') || d.name === p.name.replace(/ /g, '_')
            );
            const installLabel = isInstalled ? 'Installed' : 'Install & Use';
            const installClass = isInstalled ? 'lab-precon-card-installed' : '';

            return `
            <div class="lab-precon-card ${installClass}" onclick="AiLab.installPrecon('${escapeAttr(p.fileName)}')">
                <div class="precon-card-colors">${colors}</div>
                <div class="precon-card-name">${escapeHtml(p.name)}</div>
                <div class="precon-card-commander">${escapeHtml(p.commander)}</div>
                <div class="precon-card-set">${escapeHtml(p.set)} (${p.year})</div>
                <div class="precon-card-theme">${escapeHtml(p.theme || '')}</div>
                <button class="lab-precon-install-btn" title="Install to Forge and add to deck list">
                    ${installLabel}
                </button>
            </div>`;
        }).join('');
    }

    async function installPrecon(fileName) {
        const statusEl = document.getElementById('lab-precon-status');

        if (!backendAvailable) {
            showImportStatus(statusEl, 'Precon install requires a running backend.', 'error');
            return;
        }

        const precon = preconDecks.find(p => p.fileName === fileName);
        const displayName = precon ? precon.name : fileName;
        showImportStatus(statusEl, `Installing ${displayName}...`, 'loading');

        try {
            const res = await fetch(`${API_BASE}/api/lab/precons/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fileName }),
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Install failed');
            }

            const deckName = data.deckName;

            importedDeckMeta[deckName] = {
                source: 'Precon',
                sourceUrl: null,
                commander: precon ? precon.commander : null,
                archetype: precon ? precon.theme : null,
                colorIdentity: precon ? precon.colors : [],
            };

            if (!availableDecks.find(d => d.name === deckName)) {
                availableDecks.unshift({
                    name: deckName,
                    commander: precon ? precon.commander : deckName,
                });
                refreshDeckSelectors();
            }

            // Auto-assign to first empty seat
            const emptySeat = selectedDecks.indexOf(null);
            if (emptySeat >= 0) {
                const sel = document.getElementById(`lab-deck-select-${emptySeat}`);
                if (sel) {
                    sel.value = deckName;
                    selectDeck(emptySeat, deckName);
                }
            }

            showImportStatus(statusEl, `Installed "${displayName}" \u2014 added to deck list`, 'success');
            renderPreconGrid(preconDecks);

        } catch (err) {
            showImportStatus(statusEl, `Error: ${err.message}`, 'error');
        }
    }

    async function installAllPrecons() {
        const statusEl = document.getElementById('lab-precon-status');

        if (!backendAvailable) {
            showImportStatus(statusEl, 'Precon install requires a running backend.', 'error');
            return;
        }

        showImportStatus(statusEl, `Installing all ${preconDecks.length} precon decks...`, 'loading');

        try {
            const fileNames = preconDecks.map(p => p.fileName);
            const res = await fetch(`${API_BASE}/api/lab/precons/install-batch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fileNames }),
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Batch install failed');
            }

            let installed = 0;
            for (const r of (data.results || [])) {
                if (r.installed) {
                    installed++;
                    const deckName = r.deckName;
                    const precon = preconDecks.find(p => p.fileName === r.fileName);

                    importedDeckMeta[deckName] = {
                        source: 'Precon',
                        sourceUrl: null,
                        commander: precon ? precon.commander : null,
                        archetype: precon ? precon.theme : null,
                        colorIdentity: precon ? precon.colors : [],
                    };

                    if (!availableDecks.find(d => d.name === deckName)) {
                        availableDecks.push({
                            name: deckName,
                            commander: precon ? precon.commander : deckName,
                        });
                    }
                }
            }

            refreshDeckSelectors();
            renderPreconGrid(preconDecks);
            showImportStatus(statusEl, `Installed ${installed} of ${fileNames.length} precon decks`, 'success');

        } catch (err) {
            showImportStatus(statusEl, `Error: ${err.message}`, 'error');
        }
    }

    // ── v3: Text Import ───────────────────────────────────

    function showTextImport() {
        const modal = document.getElementById('lab-text-modal');
        if (modal) {
            modal.classList.add('active');
            document.getElementById('lab-text-import-area')?.focus();
        }
    }

    function closeTextImport() {
        const modal = document.getElementById('lab-text-modal');
        if (modal) modal.classList.remove('active');
        const statusEl = document.getElementById('lab-text-import-status');
        if (statusEl) statusEl.innerHTML = '';
    }

    async function importFromText() {
        const textArea = document.getElementById('lab-text-import-area');
        const commanderInput = document.getElementById('lab-text-commander-override');
        const statusEl = document.getElementById('lab-text-import-status');

        const text = textArea?.value.trim();
        const commander = commanderInput?.value.trim() || null;

        if (!text) {
            showImportStatus(statusEl, 'Please paste a card list.', 'error');
            return;
        }

        if (!backendAvailable) {
            showImportStatus(statusEl, 'Text import requires a running backend.', 'error');
            return;
        }

        showImportStatus(statusEl, 'Parsing card list...', 'loading');

        try {
            const res = await fetch(`${API_BASE}/api/lab/import/text`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, commander }),
            });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || 'Import failed');
            }

            importedDeckMeta[data.dckFile] = {
                source: 'Text Import',
                sourceUrl: null,
                commander: data.commander,
            };

            if (!availableDecks.find(d => d.name === data.dckFile)) {
                availableDecks.unshift({
                    name: data.dckFile,
                    commander: data.commander,
                });
                refreshDeckSelectors();
            }

            showImportStatus(statusEl,
                `Imported "${data.deckName}" (${data.totalCards} cards)`,
                'success'
            );
            textArea.value = '';
            if (commanderInput) commanderInput.value = '';

        } catch (err) {
            showImportStatus(statusEl, `Error: ${err.message}`, 'error');
        }
    }

    // ── Import Status Helper ──────────────────────────────

    function showImportStatus(el, message, type) {
        if (!el) return;
        el.className = 'lab-import-status';
        if (type) el.classList.add(`status-${type}`);
        el.innerHTML = message;
        el.style.display = 'block';

        if (type === 'success') {
            setTimeout(() => {
                if (el.innerHTML === message) el.style.display = 'none';
            }, 8000);
        }
    }

    // ── Controls ───────────────────────────────────────────

    function setGameCount(n) {
        document.getElementById('lab-game-count').value = n;
        document.querySelectorAll('.lab-preset-btn').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.textContent) === n);
        });
    }

    // ── Batch Execution ────────────────────────────────────

    async function startBatch() {
        // Validate 3 decks selected
        if (selectedDecks.some(d => !d)) {
            alert('Select a deck for all 3 seats.');
            return;
        }

        const numGames = parseInt(document.getElementById('lab-game-count').value) || 100;
        const threads = parseInt(document.getElementById('lab-threads').value) || 4;
        const seedInput = document.getElementById('lab-seed').value.trim();
        const seed = seedInput ? parseInt(seedInput) : null;

        // Build source metadata for each deck
        const deckSources = selectedDecks.map(name => {
            const meta = importedDeckMeta[name];
            return meta ? {
                source: meta.source,
                sourceUrl: meta.sourceUrl || null,
                commander: meta.commander || null,
                archetype: meta.archetype || null,
            } : {};
        });

        setRunning(true);
        clearLog();
        showProgress();

        if (backendAvailable) {
            await startBackendBatch(numGames, threads, seed, deckSources);
        } else {
            console.warn('[AI Lab] No backend — running local simulation');
            runLocalSimulation(numGames, seed);
        }
    }

    async function startBackendBatch(numGames, threads, seed, deckSources) {
        try {
            const res = await fetch(`${API_BASE}/api/lab/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    decks: selectedDecks,
                    numGames,
                    threads,
                    seed,
                    deckSources,
                }),
            });

            if (res.ok) {
                const data = await res.json();
                appendLog(`Batch ${data.batchId} started: ${numGames} games, ${threads} threads`);
                startPolling(data.batchId);
                startLogPolling(data.batchId);
            } else {
                const err = await res.text();
                appendLog(`ERROR: ${err}`);
                setRunning(false);
            }
        } catch (err) {
            appendLog(`Connection error: ${err.message}`);
            console.warn('[AI Lab] Backend error, falling back to local sim:', err);
            backendAvailable = false;
            updateBackendIndicator();
            runLocalSimulation(numGames, null);
        }
    }

    /**
     * Local simulation fallback — generates synthetic results
     * for testing the UI without a running Forge backend.
     */
    function runLocalSimulation(numGames, seed) {
        const rng = seed !== null ? seededRandom(seed) : Math.random;

        const games = [];
        let startTime = performance.now();
        let completed = 0;

        const batchInterval = setInterval(() => {
            const chunk = Math.min(Math.ceil(numGames / 20), numGames - completed);
            for (let i = 0; i < chunk && completed < numGames; i++) {
                games.push(simulateOneGame(completed, rng));
                completed++;
            }
            updateProgress(completed, numGames, performance.now() - startTime);
            appendLog(`[Game ${completed}/${numGames}] simulated locally`);

            if (completed >= numGames) {
                clearInterval(batchInterval);
                const elapsed = performance.now() - startTime;
                finalizeBatch(games, elapsed, numGames, seed);
            }
        }, 50);
    }

    function simulateOneGame(index, rng) {
        const totalTurns = Math.floor(rng() * 20) + 5;
        const winningSeat = rng() < 0.05 ? null : Math.floor(rng() * 3);

        const winConditions = ['combat_damage', 'commander_damage', 'combo_alt_win', 'life_drain'];
        const winCondition = winningSeat !== null
            ? winConditions[Math.floor(rng() * winConditions.length)]
            : 'timeout';

        const playerResults = [0, 1, 2].map(seat => ({
            seatIndex: seat,
            finalLife: seat === winningSeat ? Math.floor(rng() * 30) + 10 : Math.floor(rng() * 20) - 10,
            mulligans: rng() < 0.3 ? 1 : 0,
            isWinner: seat === winningSeat,
            commanderDamageDealt: Math.floor(rng() * 15),
            commanderCasts: Math.floor(rng() * 3),
            landsPlayed: Math.floor(totalTurns * 0.6),
            spellsCast: Math.floor(totalTurns * 1.5),
            creaturesDestroyed: Math.floor(rng() * 5),
        }));

        return {
            gameIndex: index,
            winningSeat,
            totalTurns,
            winCondition,
            gameSeed: Math.floor(rng() * 1000000),
            elapsedMs: Math.floor(rng() * 3000) + 500,
            playerResults,
        };
    }

    function finalizeBatch(games, elapsedMs, numGames, seed) {
        const summary = computeLocalSummary(games, elapsedMs);

        lastResult = {
            metadata: {
                schemaVersion: '1.0.0',
                batchId: crypto.randomUUID?.() || 'local-' + Date.now(),
                timestamp: new Date().toISOString(),
                totalGames: numGames,
                completedGames: games.length,
                format: 'commander',
                podSize: 3,
                engineVersion: backendAvailable ? 'forge-2.0.12-SNAPSHOT' : 'local-sim-1.0',
                masterSeed: seed,
                threads: 1,
                elapsedMs: Math.round(elapsedMs),
            },
            decks: selectedDecks.map((name, i) => {
                const meta = importedDeckMeta[name];
                return {
                    seatIndex: i,
                    deckName: name.replace('.dck', ''),
                    commanderName: meta?.commander || name.replace('.dck', '').replace(/_/g, ' '),
                    deckFile: name,
                    colorIdentity: meta?.colorIdentity || [],
                    cardCount: 100,
                    source: meta?.source || 'Local File',
                    sourceUrl: meta?.sourceUrl || null,
                };
            }),
            games,
            summary,
        };

        displayResults(lastResult);
        setRunning(false);
    }

    function computeLocalSummary(games, elapsedMs) {
        const perDeck = [0, 1, 2].map(seat => {
            const seatGames = games.map(g => g.playerResults[seat]);
            const wins = seatGames.filter(p => p.isWinner).length;
            const losses = games.filter(g => g.winningSeat !== null && g.winningSeat !== seat).length;
            const draws = games.filter(g => g.winningSeat === null).length;
            const winGames = games.filter(g => g.winningSeat === seat);

            const breakdown = { combat_damage: 0, commander_damage: 0, combo_alt_win: 0, life_drain: 0, mill: 0, concession: 0, timeout: 0, unknown: 0 };
            winGames.forEach(g => { breakdown[g.winCondition] = (breakdown[g.winCondition] || 0) + 1; });

            return {
                seatIndex: seat,
                deckName: selectedDecks[seat]?.replace('.dck', '') || `Deck ${seat + 1}`,
                wins,
                losses,
                draws,
                winRate: games.length > 0 ? wins / games.length : 0,
                avgTurnsToWin: wins > 0 ? winGames.reduce((s, g) => s + g.totalTurns, 0) / wins : null,
                avgMulligans: seatGames.length > 0 ? seatGames.reduce((s, p) => s + p.mulligans, 0) / seatGames.length : 0,
                avgFinalLife: seatGames.length > 0 ? seatGames.reduce((s, p) => s + p.finalLife, 0) / seatGames.length : 0,
                winConditionBreakdown: breakdown,
            };
        });

        const totalTurns = games.reduce((s, g) => s + g.totalTurns, 0);
        const totalTime = games.reduce((s, g) => s + g.elapsedMs, 0);

        return {
            perDeck,
            avgGameTurns: games.length > 0 ? totalTurns / games.length : 0,
            avgGameTimeMs: games.length > 0 ? totalTime / games.length : 0,
            simsPerSecond: elapsedMs > 0 ? (games.length / (elapsedMs / 1000)) : 0,
        };
    }

    // ── Polling ────────────────────────────────────────────

    function startPolling(batchId) {
        pollInterval = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/api/lab/status?batchId=${batchId}`);
                if (!res.ok) return;
                const data = await res.json();

                updateProgress(data.completed, data.total, data.elapsedMs);

                if (!data.running) {
                    stopPolling();

                    if (data.error) {
                        appendLog(`ERROR: ${data.error}`);
                        setRunning(false);
                        return;
                    }

                    // Fetch final result
                    const resultRes = await fetch(`${API_BASE}/api/lab/result?batchId=${batchId}`);
                    if (resultRes.ok) {
                        lastResult = await resultRes.json();
                        displayResults(lastResult);
                        appendLog(`Batch complete. ${lastResult.metadata.completedGames} games in ${(lastResult.metadata.elapsedMs/1000).toFixed(1)}s`);
                    }
                    setRunning(false);
                }
            } catch (err) {
                console.error('[AI Lab] Poll error:', err);
            }
        }, POLL_RATE_MS);
    }

    function startLogPolling(batchId) {
        logInterval = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/api/lab/log?batchId=${batchId}`);
                if (!res.ok) return;
                const data = await res.json();
                const logEl = document.getElementById('lab-log-content');
                if (logEl && data.lines) {
                    // Show last N lines
                    const tail = data.lines.slice(-30);
                    logEl.textContent = tail.join('\n');
                    logEl.scrollTop = logEl.scrollHeight;
                }
            } catch { /* ignore */ }
        }, LOG_RATE_MS);
    }

    function stopPolling() {
        if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
        if (logInterval) { clearInterval(logInterval); logInterval = null; }
    }

    // ── Progress ───────────────────────────────────────────

    function showProgress() {
        const progressEl = document.getElementById('lab-progress');
        if (progressEl) progressEl.classList.add('active');
    }

    function updateProgress(completed, total, elapsedMs) {
        const pct = total > 0 ? (completed / total) * 100 : 0;
        const fillEl = document.getElementById('lab-progress-fill');
        const countEl = document.getElementById('lab-progress-count');
        const etaEl = document.getElementById('lab-progress-eta');

        if (fillEl) fillEl.style.width = pct + '%';
        if (countEl) countEl.textContent = `${completed} / ${total} games`;

        if (completed > 0 && elapsedMs > 0) {
            const rate = completed / (elapsedMs / 1000);
            const remaining = (total - completed) / rate;
            if (etaEl) etaEl.textContent = remaining > 0 ? `~${Math.ceil(remaining)}s remaining` : 'Done';
        }
    }

    // ── Log Panel ──────────────────────────────────────────

    function clearLog() {
        const logEl = document.getElementById('lab-log-content');
        if (logEl) logEl.textContent = '';
    }

    function appendLog(msg) {
        const logEl = document.getElementById('lab-log-content');
        const logContainer = document.getElementById('lab-log');
        if (!logEl) return;
        logEl.textContent += msg + '\n';
        logEl.scrollTop = logEl.scrollHeight;
        if (logContainer) logContainer.classList.add('active');
    }

    function toggleLog() {
        const logContainer = document.getElementById('lab-log');
        const toggleBtn = document.getElementById('lab-log-toggle');
        if (logContainer) {
            logContainer.classList.toggle('collapsed');
            if (toggleBtn) toggleBtn.textContent = logContainer.classList.contains('collapsed') ? '▶' : '▼';
        }
    }

    // ── Display Results ────────────────────────────────────

    function displayResults(result) {
        const resultsEl = document.getElementById('lab-results');
        const cardsEl = document.getElementById('lab-stats-cards');
        const globalEl = document.getElementById('lab-global-stats');

        if (!resultsEl || !cardsEl || !globalEl) return;
        resultsEl.classList.add('active');

        // Sort decks by win rate for ranking
        const ranked = [...result.summary.perDeck].sort((a, b) => b.winRate - a.winRate);
        const rankMap = {};
        ranked.forEach((d, i) => { rankMap[d.seatIndex] = i + 1; });

        // Render stat cards
        cardsEl.innerHTML = result.summary.perDeck.map(ds => {
            const rank = rankMap[ds.seatIndex];
            const isWinner = rank === 1;
            const deckInfo = result.decks[ds.seatIndex];
            const breakdown = ds.winConditionBreakdown || {};

            // v3: Source badge in results
            const source = deckInfo.source || '';
            const sourceUrl = deckInfo.sourceUrl || '';
            const sourceBadgeHtml = source
                ? `<div class="lab-result-source">${renderSourceBadge(source, sourceUrl)}</div>`
                : '';

            return `
            <div class="lab-stat-card ${isWinner ? 'winner' : ''}">
                <div class="rank">#${rank}</div>
                <div class="card-deck-name">${escapeHtml(ds.deckName)}</div>
                <div class="card-commander">${escapeHtml(deckInfo.commanderName)}</div>
                ${sourceBadgeHtml}

                <div class="lab-stat-row">
                    <span class="stat-label">Win Rate</span>
                    <span class="stat-value highlight">${(ds.winRate * 100).toFixed(1)}%</span>
                </div>
                <div class="lab-stat-row">
                    <span class="stat-label">Record</span>
                    <span class="stat-value">${ds.wins}W / ${ds.losses}L / ${ds.draws}D</span>
                </div>
                <div class="lab-stat-row">
                    <span class="stat-label">Avg Turns to Win</span>
                    <span class="stat-value">${ds.avgTurnsToWin !== null ? ds.avgTurnsToWin.toFixed(1) : 'N/A'}</span>
                </div>
                <div class="lab-stat-row">
                    <span class="stat-label">Avg Mulligans</span>
                    <span class="stat-value">${ds.avgMulligans.toFixed(2)}</span>
                </div>
                <div class="lab-stat-row">
                    <span class="stat-label">Avg Final Life</span>
                    <span class="stat-value">${ds.avgFinalLife.toFixed(1)}</span>
                </div>

                <div class="lab-winrate-bar">
                    <div class="lab-winrate-fill seat-${ds.seatIndex}-color"
                         style="width: ${(ds.winRate * 100).toFixed(1)}%"></div>
                </div>

                ${ds.wins > 0 ? `
                <div class="lab-win-conditions">
                    ${Object.entries(breakdown).filter(([_, v]) => v > 0).map(([k, v]) => `
                        <span class="lab-wc-chip"><span class="wc-count">${v}</span> ${formatWinCondition(k)}</span>
                    `).join('')}
                </div>
                ` : ''}
            </div>
            `;
        }).join('');

        // Render global stats
        const s = result.summary;
        const m = result.metadata;
        globalEl.innerHTML = `
            <div class="lab-global-stat">
                <span class="g-value">${m.completedGames}</span>
                <span class="g-label">Games</span>
            </div>
            <div class="lab-global-stat">
                <span class="g-value">${s.avgGameTurns.toFixed(1)}</span>
                <span class="g-label">Avg Turns</span>
            </div>
            <div class="lab-global-stat">
                <span class="g-value">${(m.elapsedMs / 1000).toFixed(1)}s</span>
                <span class="g-label">Wall Time</span>
            </div>
            <div class="lab-global-stat">
                <span class="g-value">${s.simsPerSecond.toFixed(2)}</span>
                <span class="g-label">Sims/sec</span>
            </div>
            <div class="lab-global-stat">
                <span class="g-value">${m.threads}</span>
                <span class="g-label">Threads</span>
            </div>
            <div class="lab-global-stat">
                <span class="g-value">${m.engineVersion || '?'}</span>
                <span class="g-label">Engine</span>
            </div>
        `;

        // Render enhanced result sections
        renderCharts(result);
        renderHeadToHead(result);
        renderCombatStats(result);
        renderGameLog(result);
    }

    // ── Tab Switching ──────────────────────────────────────

    function switchTab(tabId) {
        document.querySelectorAll('.lab-tab').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabId);
        });
        document.querySelectorAll('.lab-tab-panel').forEach(panel => {
            panel.classList.toggle('active', panel.id === tabId);
        });
    }

    // ── Charts & Visualizations ────────────────────────────

    const SEAT_COLORS = ['#58a6ff', '#f85149', '#3fb950'];
    const SEAT_COLORS_DIM = ['rgba(88,166,255,0.3)', 'rgba(248,81,73,0.3)', 'rgba(63,185,80,0.3)'];

    function renderCharts(result) {
        const games = result.games || [];
        const perDeck = result.summary.perDeck || [];
        const decks = result.decks || [];

        drawWinRateChart(perDeck, decks);
        drawWinConditionChart(perDeck, decks);
        drawTurnDistribution(games, decks);
        drawWinRateTrend(games, decks);
    }

    function drawWinRateChart(perDeck, decks) {
        const canvas = document.getElementById('lab-chart-winrate');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        const pad = { top: 20, right: 20, bottom: 50, left: 50 };
        const chartW = w - pad.left - pad.right;
        const chartH = h - pad.top - pad.bottom;
        const barW = Math.min(60, chartW / perDeck.length - 20);

        // Axes
        ctx.strokeStyle = '#30363d';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top);
        ctx.lineTo(pad.left, h - pad.bottom);
        ctx.lineTo(w - pad.right, h - pad.bottom);
        ctx.stroke();

        // Y-axis labels (0%, 25%, 50%, 75%, 100%)
        ctx.fillStyle = '#8b949e';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'right';
        for (let pct = 0; pct <= 100; pct += 25) {
            const y = h - pad.bottom - (pct / 100) * chartH;
            ctx.fillText(pct + '%', pad.left - 8, y + 4);
            if (pct > 0) {
                ctx.strokeStyle = 'rgba(48,54,61,0.5)';
                ctx.beginPath();
                ctx.moveTo(pad.left, y);
                ctx.lineTo(w - pad.right, y);
                ctx.stroke();
            }
        }

        // Bars
        perDeck.forEach((ds, i) => {
            const x = pad.left + (i + 0.5) * (chartW / perDeck.length) - barW / 2;
            const barH = (ds.winRate) * chartH;
            const y = h - pad.bottom - barH;

            // Bar fill
            ctx.fillStyle = SEAT_COLORS[ds.seatIndex] || SEAT_COLORS[0];
            ctx.beginPath();
            roundRect(ctx, x, y, barW, barH, 4);
            ctx.fill();

            // Value on top
            ctx.fillStyle = '#c9d1d9';
            ctx.font = 'bold 12px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText((ds.winRate * 100).toFixed(1) + '%', x + barW / 2, y - 6);

            // Label
            ctx.fillStyle = '#8b949e';
            ctx.font = '10px -apple-system, sans-serif';
            const label = (decks[ds.seatIndex]?.commanderName || ds.deckName || '').substring(0, 16);
            ctx.fillText(label, x + barW / 2, h - pad.bottom + 14);
        });
    }

    function drawWinConditionChart(perDeck, decks) {
        const canvas = document.getElementById('lab-chart-wincond');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        // Aggregate win conditions across all decks
        const totals = {};
        perDeck.forEach(ds => {
            const bd = ds.winConditionBreakdown || {};
            Object.entries(bd).forEach(([k, v]) => {
                if (v > 0) totals[k] = (totals[k] || 0) + v;
            });
        });

        const entries = Object.entries(totals).filter(([_, v]) => v > 0).sort((a, b) => b[1] - a[1]);
        if (entries.length === 0) {
            ctx.fillStyle = '#8b949e';
            ctx.font = '13px -apple-system, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('No win data', w / 2, h / 2);
            return;
        }

        const total = entries.reduce((s, [_, v]) => s + v, 0);
        const pieColors = ['#58a6ff', '#f85149', '#3fb950', '#d29922', '#a371f7', '#f0883e', '#8b949e', '#56d364'];
        const cx = w * 0.35, cy = h / 2, radius = Math.min(cx - 20, cy - 20);

        let startAngle = -Math.PI / 2;
        const slices = [];
        entries.forEach(([k, v], i) => {
            const sliceAngle = (v / total) * Math.PI * 2;
            ctx.fillStyle = pieColors[i % pieColors.length];
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.arc(cx, cy, radius, startAngle, startAngle + sliceAngle);
            ctx.closePath();
            ctx.fill();
            slices.push({ key: k, value: v, color: pieColors[i % pieColors.length], startAngle, endAngle: startAngle + sliceAngle });
            startAngle += sliceAngle;
        });

        // Legend
        const legendX = w * 0.65;
        let legendY = 30;
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'left';
        slices.forEach(s => {
            ctx.fillStyle = s.color;
            ctx.fillRect(legendX, legendY - 8, 10, 10);
            ctx.fillStyle = '#c9d1d9';
            const pct = ((s.value / total) * 100).toFixed(0);
            ctx.fillText(`${formatWinCondition(s.key)} (${pct}%)`, legendX + 16, legendY);
            legendY += 18;
        });
    }

    function drawTurnDistribution(games, decks) {
        const canvas = document.getElementById('lab-chart-turns');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        if (games.length === 0) return;

        const pad = { top: 20, right: 20, bottom: 50, left: 50 };
        const chartW = w - pad.left - pad.right;
        const chartH = h - pad.top - pad.bottom;

        // Build histogram buckets
        const turns = games.map(g => g.totalTurns);
        const minT = Math.min(...turns);
        const maxT = Math.max(...turns);
        const bucketSize = Math.max(1, Math.ceil((maxT - minT + 1) / 15));
        const buckets = [];
        for (let t = minT; t <= maxT; t += bucketSize) {
            const count = turns.filter(v => v >= t && v < t + bucketSize).length;
            buckets.push({ label: bucketSize === 1 ? '' + t : t + '-' + (t + bucketSize - 1), count });
        }

        const maxCount = Math.max(...buckets.map(b => b.count));
        const barW = Math.max(4, chartW / buckets.length - 2);

        // Axes
        ctx.strokeStyle = '#30363d';
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top);
        ctx.lineTo(pad.left, h - pad.bottom);
        ctx.lineTo(w - pad.right, h - pad.bottom);
        ctx.stroke();

        // Y-axis
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px -apple-system, sans-serif';
        ctx.textAlign = 'right';
        for (let i = 0; i <= 4; i++) {
            const val = Math.round(maxCount * i / 4);
            const y = h - pad.bottom - (i / 4) * chartH;
            ctx.fillText(val, pad.left - 8, y + 3);
        }

        // Bars
        buckets.forEach((b, i) => {
            const x = pad.left + i * (chartW / buckets.length) + 1;
            const barH = maxCount > 0 ? (b.count / maxCount) * chartH : 0;
            const y = h - pad.bottom - barH;

            ctx.fillStyle = '#58a6ff';
            ctx.globalAlpha = 0.8;
            ctx.beginPath();
            roundRect(ctx, x, y, barW, barH, 2);
            ctx.fill();
            ctx.globalAlpha = 1;

            // Label
            if (buckets.length <= 20) {
                ctx.fillStyle = '#8b949e';
                ctx.font = '9px -apple-system, sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(b.label, x + barW / 2, h - pad.bottom + 14);
            }
        });

        // X-axis label
        ctx.fillStyle = '#8b949e';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Turns', w / 2, h - 6);
    }

    function drawWinRateTrend(games, decks) {
        const canvas = document.getElementById('lab-chart-wintrend');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const w = canvas.width, h = canvas.height;
        ctx.clearRect(0, 0, w, h);

        if (games.length < 2) return;

        const pad = { top: 20, right: 20, bottom: 50, left: 50 };
        const chartW = w - pad.left - pad.right;
        const chartH = h - pad.top - pad.bottom;

        // Compute cumulative win rate for each seat
        const seatWins = [0, 0, 0];
        const seatRates = [[], [], []];

        // Sample points (don't plot every game for large batches)
        const step = Math.max(1, Math.floor(games.length / 100));

        games.forEach((g, gi) => {
            if (g.winningSeat !== null && g.winningSeat !== undefined) {
                seatWins[g.winningSeat]++;
            }
            if (gi % step === 0 || gi === games.length - 1) {
                const n = gi + 1;
                for (let s = 0; s < 3; s++) {
                    seatRates[s].push({ x: gi, y: seatWins[s] / n });
                }
            }
        });

        // Axes
        ctx.strokeStyle = '#30363d';
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top);
        ctx.lineTo(pad.left, h - pad.bottom);
        ctx.lineTo(w - pad.right, h - pad.bottom);
        ctx.stroke();

        // Y-axis labels
        ctx.fillStyle = '#8b949e';
        ctx.font = '10px -apple-system, sans-serif';
        ctx.textAlign = 'right';
        for (let pct = 0; pct <= 100; pct += 25) {
            const y = h - pad.bottom - (pct / 100) * chartH;
            ctx.fillText(pct + '%', pad.left - 8, y + 3);
            ctx.strokeStyle = 'rgba(48,54,61,0.3)';
            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(w - pad.right, y);
            ctx.stroke();
        }

        // Lines
        const maxX = games.length - 1;
        for (let s = 0; s < 3; s++) {
            const points = seatRates[s];
            if (points.length < 2) continue;

            ctx.strokeStyle = SEAT_COLORS[s];
            ctx.lineWidth = 2;
            ctx.beginPath();
            points.forEach((p, pi) => {
                const px = pad.left + (p.x / maxX) * chartW;
                const py = h - pad.bottom - p.y * chartH;
                if (pi === 0) ctx.moveTo(px, py);
                else ctx.lineTo(px, py);
            });
            ctx.stroke();
            ctx.lineWidth = 1;
        }

        // Legend
        ctx.font = '10px -apple-system, sans-serif';
        ctx.textAlign = 'left';
        for (let s = 0; s < 3; s++) {
            const lx = pad.left + 10 + s * 120;
            ctx.fillStyle = SEAT_COLORS[s];
            ctx.fillRect(lx, pad.top + 2, 12, 3);
            ctx.fillStyle = '#8b949e';
            const label = (decks[s]?.commanderName || decks[s]?.deckName || 'Deck ' + (s + 1)).substring(0, 14);
            ctx.fillText(label, lx + 16, pad.top + 7);
        }

        // X-axis label
        ctx.fillStyle = '#8b949e';
        ctx.font = '11px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Games Played', w / 2, h - 6);
    }

    function roundRect(ctx, x, y, w, h, r) {
        if (h <= 0) { ctx.rect(x, y, w, 0); return; }
        r = Math.min(r, h / 2, w / 2);
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
    }

    // ── Head-to-Head Matrix ────────────────────────────────

    function renderHeadToHead(result) {
        const el = document.getElementById('lab-h2h-matrix');
        if (!el) return;

        const games = result.games || [];
        const decks = result.decks || [];
        if (games.length === 0) { el.innerHTML = '<p class="lab-no-data">No game data</p>'; return; }

        // Compute pairwise: for each pair (A, B), how often did A win when both were in the game (always — 3-player pod)
        // Show: when deck A wins, what % of those games vs each opponent
        // Better metric: For each pair, count games where A wins and B doesn't (and vice versa)
        const n = decks.length;
        const h2h = Array.from({ length: n }, () => Array(n).fill(0));
        const pairGames = Array.from({ length: n }, () => Array(n).fill(0));

        games.forEach(g => {
            for (let a = 0; a < n; a++) {
                for (let b = 0; b < n; b++) {
                    if (a === b) continue;
                    pairGames[a][b]++;
                    if (g.winningSeat === a) h2h[a][b]++;
                }
            }
        });

        let html = '<table class="lab-h2h-table"><thead><tr><th class="lab-h2h-corner">vs</th>';
        decks.forEach((d, i) => {
            const name = (d.commanderName || d.deckName || 'Deck ' + (i + 1)).substring(0, 18);
            html += `<th style="color:${SEAT_COLORS[i]}">${escapeHtml(name)}</th>`;
        });
        html += '</tr></thead><tbody>';

        for (let a = 0; a < n; a++) {
            const name = (decks[a].commanderName || decks[a].deckName || 'Deck ' + (a + 1)).substring(0, 18);
            html += `<tr><td class="lab-h2h-row-label" style="color:${SEAT_COLORS[a]}">${escapeHtml(name)}</td>`;
            for (let b = 0; b < n; b++) {
                if (a === b) {
                    html += '<td class="lab-h2h-self">—</td>';
                } else {
                    const wins = h2h[a][b];
                    const total = pairGames[a][b];
                    const rate = total > 0 ? (wins / total * 100).toFixed(1) : '0.0';
                    const rateNum = total > 0 ? wins / total : 0;
                    const cls = rateNum > 0.5 ? 'lab-h2h-winning' : rateNum < 0.3 ? 'lab-h2h-losing' : '';
                    html += `<td class="lab-h2h-cell ${cls}">${rate}%<span class="lab-h2h-sub">${wins}/${total}</span></td>`;
                }
            }
            html += '</tr>';
        }
        html += '</tbody></table>';

        html += '<p class="lab-h2h-note">Reads as: row deck\'s win rate in games where column deck also played.</p>';
        el.innerHTML = html;
    }

    // ── Combat Stats ──────────────────────────────────────

    function renderCombatStats(result) {
        const el = document.getElementById('lab-combat-stats');
        if (!el) return;

        const games = result.games || [];
        const decks = result.decks || [];
        if (games.length === 0) { el.innerHTML = '<p class="lab-no-data">No game data</p>'; return; }

        // Aggregate per-seat combat stats from game-level playerResults
        const stats = decks.map((d, seat) => {
            const pr = games.map(g => g.playerResults[seat]).filter(Boolean);
            const n = pr.length;
            if (n === 0) return null;

            const sum = (fn) => pr.reduce((s, p) => s + fn(p), 0);
            const avg = (fn) => sum(fn) / n;
            const max = (fn) => Math.max(...pr.map(fn));

            return {
                seat,
                name: d.commanderName || d.deckName || 'Deck ' + (seat + 1),
                avgCmdrDmg: avg(p => p.commanderDamageDealt || 0),
                maxCmdrDmg: max(p => p.commanderDamageDealt || 0),
                avgCmdrCasts: avg(p => p.commanderCasts || 0),
                maxCmdrCasts: max(p => p.commanderCasts || 0),
                avgLands: avg(p => p.landsPlayed || 0),
                avgSpells: avg(p => p.spellsCast || 0),
                maxSpells: max(p => p.spellsCast || 0),
                avgCreaturesDestroyed: avg(p => p.creaturesDestroyed || 0),
                totalCreaturesDestroyed: sum(p => p.creaturesDestroyed || 0),
                avgFinalLife: avg(p => p.finalLife || 0),
            };
        }).filter(Boolean);

        let html = '<div class="lab-combat-grid">';
        stats.forEach(s => {
            html += `
            <div class="lab-combat-card">
                <div class="lab-combat-header" style="border-left: 3px solid ${SEAT_COLORS[s.seat]}">
                    ${escapeHtml(s.name)}
                </div>
                <div class="lab-combat-rows">
                    <div class="lab-combat-row">
                        <span class="lab-combat-icon">⚔️</span>
                        <span class="lab-combat-label">Cmdr Damage / Game</span>
                        <span class="lab-combat-val">${s.avgCmdrDmg.toFixed(1)}</span>
                        <span class="lab-combat-max">max ${s.maxCmdrDmg}</span>
                    </div>
                    <div class="lab-combat-row">
                        <span class="lab-combat-icon">👑</span>
                        <span class="lab-combat-label">Cmdr Casts / Game</span>
                        <span class="lab-combat-val">${s.avgCmdrCasts.toFixed(2)}</span>
                        <span class="lab-combat-max">max ${s.maxCmdrCasts}</span>
                    </div>
                    <div class="lab-combat-row">
                        <span class="lab-combat-icon">🏔️</span>
                        <span class="lab-combat-label">Lands / Game</span>
                        <span class="lab-combat-val">${s.avgLands.toFixed(1)}</span>
                    </div>
                    <div class="lab-combat-row">
                        <span class="lab-combat-icon">✨</span>
                        <span class="lab-combat-label">Spells / Game</span>
                        <span class="lab-combat-val">${s.avgSpells.toFixed(1)}</span>
                        <span class="lab-combat-max">max ${s.maxSpells}</span>
                    </div>
                    <div class="lab-combat-row">
                        <span class="lab-combat-icon">💀</span>
                        <span class="lab-combat-label">Creatures Destroyed / Game</span>
                        <span class="lab-combat-val">${s.avgCreaturesDestroyed.toFixed(1)}</span>
                        <span class="lab-combat-max">total ${s.totalCreaturesDestroyed}</span>
                    </div>
                    <div class="lab-combat-row">
                        <span class="lab-combat-icon">❤️</span>
                        <span class="lab-combat-label">Avg Final Life</span>
                        <span class="lab-combat-val">${s.avgFinalLife.toFixed(1)}</span>
                    </div>
                </div>
            </div>`;
        });
        html += '</div>';
        el.innerHTML = html;
    }

    // ── Game-by-Game Log ──────────────────────────────────

    let gameLogData = [];

    function renderGameLog(result) {
        const wrapper = document.getElementById('lab-gamelog-wrapper');
        const countEl = document.getElementById('lab-gamelog-count');
        const filterInput = document.getElementById('lab-gamelog-filter');
        if (!wrapper) return;

        const games = result.games || [];
        const decks = result.decks || [];

        gameLogData = games.map(g => {
            const winnerName = g.winningSeat !== null && g.winningSeat !== undefined
                ? (decks[g.winningSeat]?.commanderName || decks[g.winningSeat]?.deckName || 'Deck ' + (g.winningSeat + 1))
                : 'Draw';
            return {
                index: g.gameIndex + 1,
                winner: winnerName,
                winningSeat: g.winningSeat,
                turns: g.totalTurns,
                winCondition: g.winCondition,
                elapsed: g.elapsedMs,
                players: g.playerResults.map((pr, i) => ({
                    name: (decks[i]?.commanderName || decks[i]?.deckName || 'Deck ' + (i + 1)).substring(0, 16),
                    life: pr.finalLife,
                    seat: i,
                    isWinner: pr.isWinner,
                })),
            };
        });

        // Wire up filter
        if (filterInput) {
            filterInput.oninput = () => filterGameLog(filterInput.value);
        }

        renderGameLogTable(gameLogData);
    }

    function filterGameLog(query) {
        const q = query.toLowerCase().trim();
        if (!q) {
            renderGameLogTable(gameLogData);
            return;
        }
        const filtered = gameLogData.filter(g =>
            g.winner.toLowerCase().includes(q) ||
            (g.winCondition || '').toLowerCase().includes(q) ||
            formatWinCondition(g.winCondition).toLowerCase().includes(q) ||
            g.players.some(p => p.name.toLowerCase().includes(q))
        );
        renderGameLogTable(filtered);
    }

    function renderGameLogTable(data) {
        const wrapper = document.getElementById('lab-gamelog-wrapper');
        const countEl = document.getElementById('lab-gamelog-count');
        if (!wrapper) return;

        if (countEl) {
            countEl.textContent = data.length + ' game' + (data.length !== 1 ? 's' : '');
        }

        // Show max 200 rows, paginated
        const pageSize = 200;
        const display = data.slice(0, pageSize);

        let html = `<table class="lab-gamelog-table">
            <thead><tr>
                <th>#</th>
                <th>Winner</th>
                <th>Turns</th>
                <th>Win Condition</th>`;
        // Life columns for each seat
        if (display.length > 0 && display[0].players) {
            display[0].players.forEach((p, i) => {
                html += `<th style="color:${SEAT_COLORS[i]}">${escapeHtml(p.name)}</th>`;
            });
        }
        html += '</tr></thead><tbody>';

        display.forEach(g => {
            const winColor = g.winningSeat !== null && g.winningSeat !== undefined
                ? SEAT_COLORS[g.winningSeat] : '#8b949e';
            html += `<tr>
                <td class="lab-gl-num">${g.index}</td>
                <td style="color:${winColor}">${escapeHtml(g.winner)}</td>
                <td>${g.turns}</td>
                <td class="lab-gl-wc">${formatWinCondition(g.winCondition)}</td>`;
            g.players.forEach(p => {
                const lifeClass = p.life <= 0 ? 'lab-gl-dead' : p.isWinner ? 'lab-gl-alive' : '';
                html += `<td class="${lifeClass}">${p.life}</td>`;
            });
            html += '</tr>';
        });
        html += '</tbody></table>';

        if (data.length > pageSize) {
            html += `<p class="lab-gl-more">Showing ${pageSize} of ${data.length} games</p>`;
        }

        wrapper.innerHTML = html;
    }

    // ── History ────────────────────────────────────────────

    async function showHistory() {
        const modal = document.getElementById('lab-history-modal');
        const listEl = document.getElementById('lab-history-list');
        if (!modal || !listEl) return;

        modal.classList.add('active');
        listEl.innerHTML = 'Loading...';

        if (!backendAvailable) {
            listEl.innerHTML = '<p class="lab-history-empty">History requires a running backend.</p>';
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/api/lab/history`);
            if (!res.ok) throw new Error('Failed to load history');
            const data = await res.json();

            if (!data.results || data.results.length === 0) {
                listEl.innerHTML = '<p class="lab-history-empty">No past runs found.</p>';
                return;
            }

            listEl.innerHTML = data.results.map(r => {
                const deckLabels = (r.decks || []).map(d => {
                    const srcTag = d.source ? ` <span class="hist-src">[${d.source}]</span>` : '';
                    return `${escapeHtml(d.name)}${srcTag}`;
                }).join(', ');

                return `
                <div class="lab-history-item" onclick="AiLab.loadHistoryResult('${r.filename}')">
                    <div class="history-batch-id">${r.batchId}</div>
                    <div class="history-meta">
                        ${r.totalGames} games · ${r.threads} threads · ${(r.elapsedMs/1000).toFixed(1)}s
                    </div>
                    <div class="history-decks">${deckLabels}</div>
                    <div class="history-time">${new Date(r.timestamp).toLocaleString()}</div>
                </div>
                `;
            }).join('');
        } catch (err) {
            listEl.innerHTML = `<p class="lab-history-empty">Error: ${err.message}</p>`;
        }
    }

    function closeHistory() {
        const modal = document.getElementById('lab-history-modal');
        if (modal) modal.classList.remove('active');
    }

    async function loadHistoryResult(filename) {
        closeHistory();
        try {
            // Fetch from results directory via API
            const batchId = filename.replace('batch-', '').replace('.json', '');
            const res = await fetch(`${API_BASE}/api/lab/result?batchId=${batchId}`);
            if (res.ok) {
                lastResult = await res.json();
                displayResults(lastResult);
            }
        } catch (err) {
            console.error('[AI Lab] Failed to load history result:', err);
        }
    }

    // ── Helpers ─────────────────────────────────────────────

    function formatWinCondition(key) {
        const map = {
            combat_damage: 'Combat',
            commander_damage: 'Cmdr Dmg',
            combo_alt_win: 'Combo',
            life_drain: 'Drain',
            mill: 'Mill',
            concession: 'Concede',
            timeout: 'Timeout',
            unknown: '???',
        };
        return map[key] || key;
    }

    function setRunning(running) {
        isRunning = running;
        const btn = document.getElementById('lab-run-btn');
        if (btn) {
            btn.disabled = running;
            btn.classList.toggle('running', running);
            btn.querySelector('.run-text').textContent = running ? 'Simulating...' : 'Run AI Sims';
        }
        if (!running) {
            stopPolling();
            // Keep progress visible briefly, then fade
            setTimeout(() => {
                const progressEl = document.getElementById('lab-progress');
                if (progressEl) progressEl.classList.remove('active');
            }, 3000);
        }
    }

    function seededRandom(seed) {
        let s = seed | 0;
        return function() {
            s |= 0; s = s + 0x6D2B79F5 | 0;
            let t = Math.imul(s ^ s >>> 15, 1 | s);
            t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
            return ((t ^ t >>> 14) >>> 0) / 4294967296;
        };
    }

    function exportJson() {
        if (!lastResult) return;
        const json = JSON.stringify(lastResult, null, 2);
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `commander-ai-lab-${lastResult.metadata.batchId}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function escapeAttr(str) {
        return str.replace(/'/g, "\\'").replace(/"/g, '\\"');
    }

    function bindEvents() {
        const input = document.getElementById('lab-game-count');
        if (input) {
            input.addEventListener('change', () => {
                document.querySelectorAll('.lab-preset-btn').forEach(btn => {
                    btn.classList.toggle('active', parseInt(btn.textContent) === parseInt(input.value));
                });
            });
        }

        // Close modals on overlay click
        document.querySelectorAll('.lab-modal-overlay').forEach(modal => {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.classList.remove('active');
                }
            });
        });

        // Enter key in URL import
        const urlInput = document.getElementById('lab-import-url-input');
        if (urlInput) {
            urlInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') importFromUrl();
            });
        }
    }

    // ── Public API ─────────────────────────────────────────

    return {
        init,
        selectDeck,
        setGameCount,
        startBatch,
        exportJson,
        showHistory,
        closeHistory,
        loadHistoryResult,
        toggleLog,
        getLastResult: () => lastResult,
        // v3
        showUrlImport,
        hideUrlImport,
        importFromUrl,
        showMetaPicker,
        closeMetaPicker,
        filterMetaCommanders,
        fetchMetaDeck,
        showTextImport,
        closeTextImport,
        importFromText,
        // Precon decks
        showPreconPicker,
        closePreconPicker,
        filterPrecons,
        installPrecon,
        installAllPrecons,
        // v4 — enhanced results
        switchTab,
    };

})();

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', AiLab.init);
} else {
    AiLab.init();
}
