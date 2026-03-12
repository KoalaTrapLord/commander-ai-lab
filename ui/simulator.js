/* ══════════════════════════════════════════════════════════════
   Commander AI Lab — Simulator Page Controller
   ══════════════════════════════════════════════════════════════ */

(function () {
    'use strict';

    // ── DOM refs ──
    const deckSelect     = document.getElementById('sim-deck-select');
    const oppSelect      = document.getElementById('sim-opponent-select');
    const numGamesInput  = document.getElementById('sim-num-games');
    const recordLogsChk  = document.getElementById('sim-record-logs');
    const runBtn         = document.getElementById('sim-run-btn');
    const pasteArea      = document.getElementById('sim-paste-decklist');
    const pasteName      = document.getElementById('sim-paste-name');
    const pasteRunBtn    = document.getElementById('sim-paste-run-btn');
    const progressEl     = document.getElementById('sim-progress');
    const progressText   = document.getElementById('sim-progress-text');
    const progressCount  = document.getElementById('sim-progress-count');
    const progressBar    = document.getElementById('sim-progress-bar');
    const resultsEl      = document.getElementById('sim-results');
    const statsGrid      = document.getElementById('sim-stats-grid');
    const gamesList      = document.getElementById('sim-games-list');

    // DeepSeek DOM refs
    const dsPanel        = document.getElementById('deepseek-panel');
    const dsStatusBadge  = document.getElementById('ds-status-badge');
    const dsConnectBtn   = document.getElementById('ds-connect-btn');
    const dsApiBase      = document.getElementById('ds-api-base');
    const dsModel        = document.getElementById('ds-model');
    const dsTemp         = document.getElementById('ds-temp');
    const dsTimeout      = document.getElementById('ds-timeout');
    const dsStatsRow     = document.getElementById('ds-stats-row');

    let currentSimId = null;
    let pollTimer    = null;
    let dsConnected  = false;

    // ── Init: load decks ──
    async function loadDecks() {
        try {
            const res = await fetch('/api/decks');
            if (!res.ok) return;
            const data = await res.json();
            const decks = data.decks || data || [];
            decks.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.id;
                opt.textContent = d.name + (d.commander ? ' (' + d.commander + ')' : '');
                deckSelect.appendChild(opt);
            });
        } catch (e) {
            console.warn('Could not load decks:', e);
        }
    }

    deckSelect.addEventListener('change', () => {
        runBtn.disabled = !deckSelect.value;
    });

    // ── Opponent selector ──
    oppSelect.addEventListener('change', () => {
        const isDeepSeek = oppSelect.value === 'deepseek';
        dsPanel.style.display = isDeepSeek ? 'block' : 'none';
        if (isDeepSeek) {
            // Auto-cap games for DeepSeek (LLM is slower)
            if (parseInt(numGamesInput.value) > 50) {
                numGamesInput.value = 5;
            }
            numGamesInput.max = 50;
            // Check initial connection status
            checkDeepSeekStatus();
        } else {
            numGamesInput.max = 1000;
        }
    });

    // ── DeepSeek connection ──
    dsConnectBtn.addEventListener('click', connectDeepSeek);

    async function connectDeepSeek() {
        dsConnectBtn.disabled = true;
        dsConnectBtn.textContent = 'Connecting...';
        dsStatusBadge.className = 'ds-badge ds-badge-pending';
        dsStatusBadge.textContent = 'Connecting...';

        try {
            const payload = {};
            if (dsApiBase.value.trim()) payload.apiBase = dsApiBase.value.trim();
            if (dsModel.value.trim()) payload.model = dsModel.value.trim();

            const res = await fetch('/api/deepseek/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json();

            if (data.connected) {
                dsConnected = true;
                dsStatusBadge.className = 'ds-badge ds-badge-on';
                dsStatusBadge.textContent = 'Connected';
                dsConnectBtn.textContent = 'Reconnect';
                if (data.model) dsModel.value = data.model;

                // Apply settings
                await applyDeepSeekConfig();
                updateDeepSeekStats(data.stats);
            } else {
                dsConnected = false;
                dsStatusBadge.className = 'ds-badge ds-badge-off';
                dsStatusBadge.textContent = 'Failed';
                dsConnectBtn.textContent = 'Retry';
            }
        } catch (e) {
            dsConnected = false;
            dsStatusBadge.className = 'ds-badge ds-badge-off';
            dsStatusBadge.textContent = 'Error';
            dsConnectBtn.textContent = 'Retry';
            console.error('DeepSeek connect error:', e);
        }
        dsConnectBtn.disabled = false;
    }

    async function applyDeepSeekConfig() {
        try {
            await fetch('/api/deepseek/configure', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    temperature: parseFloat(dsTemp.value) || 0.3,
                    timeout: parseFloat(dsTimeout.value) || 10,
                }),
            });
        } catch (e) {
            console.warn('Config apply failed:', e);
        }
    }

    async function checkDeepSeekStatus() {
        try {
            const res = await fetch('/api/deepseek/status');
            const data = await res.json();
            if (data.connected) {
                dsConnected = true;
                dsStatusBadge.className = 'ds-badge ds-badge-on';
                dsStatusBadge.textContent = 'Connected';
                dsConnectBtn.textContent = 'Reconnect';
                updateDeepSeekStats(data);
            }
        } catch (e) { /* ignore */ }
    }

    function updateDeepSeekStats(stats) {
        if (!stats) return;
        dsStatsRow.style.display = 'flex';
        document.getElementById('ds-stat-calls').textContent = 'Calls: ' + (stats.total_calls || 0);
        document.getElementById('ds-stat-cache').textContent = 'Cache: ' + (stats.cache_hits || 0);
        document.getElementById('ds-stat-fallback').textContent = 'Fallbacks: ' + (stats.fallbacks || 0);
        document.getElementById('ds-stat-latency').textContent = 'Avg: ' + (stats.avg_latency_ms || 0) + 'ms';
        if (stats.model) {
            document.getElementById('ds-stat-model').textContent = stats.model;
        }
    }

    // ── Run from deck ID ──
    runBtn.addEventListener('click', async () => {
        const deckId = parseInt(deckSelect.value);
        if (!deckId) return;

        const numGames = parseInt(numGamesInput.value) || 10;
        const recordLogs = recordLogsChk.checked;
        const useDeepSeek = oppSelect.value === 'deepseek';

        // If DeepSeek selected but not connected, try to connect first
        if (useDeepSeek && !dsConnected) {
            await connectDeepSeek();
            if (!dsConnected) {
                alert('Could not connect to DeepSeek. Make sure LM Studio is running at ' + dsApiBase.value);
                return;
            }
            await applyDeepSeekConfig();
        }

        runBtn.disabled = true;
        runBtn.classList.add('running');
        runBtn.textContent = useDeepSeek ? 'Running (DeepSeek)...' : 'Running...';
        showProgress(numGames);
        hideResults();

        try {
            const endpoint = useDeepSeek ? '/api/sim/run-deepseek' : '/api/sim/run-from-deck';
            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ deckId, numGames, recordLogs }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            currentSimId = data.simId;
            startPolling();
        } catch (e) {
            alert('Error: ' + e.message);
            resetRunBtn();
        }
    });

    // ── Run from pasted decklist ──
    pasteRunBtn.addEventListener('click', async () => {
        const raw = pasteArea.value.trim();
        if (!raw) { alert('Paste a decklist first'); return; }

        const lines = raw.split('\n').filter(l => l.trim());
        const decklist = [];
        for (const line of lines) {
            const m = line.trim().match(/^(\d+)\s+(.+)$/);
            if (m) {
                const count = parseInt(m[1]);
                const name = m[2].trim();
                for (let i = 0; i < count; i++) decklist.push(name);
            } else {
                decklist.push(line.trim());
            }
        }

        const numGames = parseInt(numGamesInput.value) || 10;
        const recordLogs = recordLogsChk.checked;
        const deckName = pasteName.value.trim() || 'Custom Deck';

        pasteRunBtn.disabled = true;
        pasteRunBtn.classList.add('running');
        pasteRunBtn.textContent = 'Running...';
        showProgress(numGames);
        hideResults();

        try {
            const res = await fetch('/api/sim/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ decklist, numGames, deckName, recordLogs }),
            });
            const data = await res.json();
            if (data.error) throw new Error(data.error);
            currentSimId = data.simId;
            startPolling();
        } catch (e) {
            alert('Error: ' + e.message);
            pasteRunBtn.disabled = false;
            pasteRunBtn.classList.remove('running');
            pasteRunBtn.textContent = 'Run from Paste';
        }
    });

    // ── Polling ──
    function startPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(pollStatus, 400);
    }

    async function pollStatus() {
        if (!currentSimId) return;
        try {
            const res = await fetch('/api/sim/status?simId=' + currentSimId);
            const data = await res.json();

            updateProgress(data.completed, data.total);

            if (data.status === 'complete') {
                clearInterval(pollTimer);
                pollTimer = null;
                await loadResults(currentSimId);
                resetRunBtn();
                // Refresh DeepSeek stats if applicable
                if (oppSelect.value === 'deepseek') {
                    checkDeepSeekStatus();
                }
            } else if (data.status === 'error') {
                clearInterval(pollTimer);
                pollTimer = null;
                alert('Simulation error: ' + (data.error || 'Unknown'));
                resetRunBtn();
            }
        } catch (e) {
            console.error('Poll error:', e);
        }
    }

    async function loadResults(simId) {
        const res = await fetch('/api/sim/result?simId=' + simId);
        const data = await res.json();
        renderResults(data);
    }

    // ── Progress UI ──
    function showProgress(total) {
        progressEl.style.display = 'block';
        progressText.textContent = 'Simulating...';
        progressCount.textContent = '0 / ' + total;
        progressBar.style.width = '0%';
    }

    function updateProgress(completed, total) {
        progressCount.textContent = completed + ' / ' + total;
        const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
        progressBar.style.width = pct + '%';
        if (completed >= total) {
            progressText.textContent = 'Complete';
        }
    }

    function hideResults() {
        resultsEl.style.display = 'none';
        statsGrid.innerHTML = '';
        gamesList.innerHTML = '';
    }

    function resetRunBtn() {
        runBtn.disabled = !deckSelect.value;
        runBtn.classList.remove('running');
        runBtn.textContent = 'Run Simulation';
        pasteRunBtn.disabled = false;
        pasteRunBtn.classList.remove('running');
        pasteRunBtn.textContent = 'Run from Paste';
    }

    // ── Render Results ──
    function renderResults(data) {
        resultsEl.style.display = 'block';
        renderStats(data.summary);
        renderGames(data.games, data.summary);
    }

    function renderStats(s) {
        statsGrid.innerHTML = '';
        const cards = [
            { value: s.winRate + '%', label: 'Win Rate', cls: s.winRate >= 50 ? 'win' : 'loss', highlight: true },
            { value: s.wins + ' / ' + s.losses, label: 'Wins / Losses', cls: '' },
            { value: s.totalGames, label: 'Total Games', cls: '' },
            { value: s.avgTurns, label: 'Avg Turns', cls: '' },
            { value: s.avgDamageDealt, label: 'Avg Damage Dealt', cls: '' },
            { value: s.avgDamageReceived, label: 'Avg Damage Taken', cls: '' },
            { value: s.avgSpellsCast, label: 'Avg Spells Cast', cls: '' },
            { value: s.avgCreaturesPlayed, label: 'Avg Creatures', cls: '' },
            { value: s.avgRemovalUsed, label: 'Avg Removal Used', cls: '' },
            { value: s.avgRampPlayed, label: 'Avg Ramp Played', cls: '' },
            { value: s.avgCardsDrawn, label: 'Avg Cards Drawn', cls: '' },
            { value: s.avgMaxBoardSize, label: 'Avg Max Board', cls: '' },
        ];

        cards.forEach(c => {
            const div = document.createElement('div');
            div.className = 'sim-stat-card' + (c.highlight ? ' highlight' : '') + (c.cls ? ' ' + c.cls : '');
            div.innerHTML = '<div class="sim-stat-value">' + c.value + '</div>'
                + '<div class="sim-stat-label">' + c.label + '</div>';
            statsGrid.appendChild(div);
        });

        // Elapsed
        const el = document.createElement('div');
        el.className = 'sim-stat-card';
        el.innerHTML = '<div class="sim-stat-value">' + s.elapsedSeconds + 's</div>'
            + '<div class="sim-stat-label">Elapsed</div>';
        statsGrid.appendChild(el);

        // Opponent type badge
        if (s.opponentType === 'deepseek') {
            const dsCard = document.createElement('div');
            dsCard.className = 'sim-stat-card ds-opponent-card';
            let dsInfo = '&#129504; DeepSeek AI';
            if (s.deepseekStats) {
                const ds = s.deepseekStats;
                dsInfo += '<br><small>LLM calls: ' + (ds.llm_calls || 0)
                    + ' | Cache: ' + (ds.cache_hits || 0)
                    + ' | Fallbacks: ' + (ds.fallbacks || 0)
                    + ' | Avg: ' + (ds.avg_latency_ms || 0) + 'ms</small>';
            }
            dsCard.innerHTML = '<div class="sim-stat-value" style="font-size:0.9rem">' + dsInfo + '</div>'
                + '<div class="sim-stat-label">Opponent</div>';
            statsGrid.appendChild(dsCard);
        }
    }

    function renderGames(games, summary) {
        gamesList.innerHTML = '';

        if (!games || games.length === 0) {
            gamesList.innerHTML = '<div class="sim-no-logs">No game data available</div>';
            return;
        }

        games.forEach((g, idx) => {
            const row = document.createElement('div');
            row.className = 'sim-game-row';

            const isWin = g.winner === 0;
            const winnerName = isWin ? g.playerA.name : g.playerB.name;
            const lifeA = g.playerA.life;
            const lifeB = g.playerB.life;

            // Header
            const header = document.createElement('div');
            header.className = 'sim-game-header';
            header.innerHTML =
                '<span class="sim-game-num">Game ' + (g.gameNumber || idx + 1) + '</span>' +
                '<span class="sim-game-winner ' + (isWin ? 'win' : 'loss') + '">' +
                    (isWin ? 'WIN' : 'LOSS') + ' — ' + winnerName + ' wins' +
                '</span>' +
                '<span class="sim-game-info">' +
                    '<span>' + g.turns + ' turns</span>' +
                    '<span>' + g.playerA.name + ': ' + lifeA + ' life</span>' +
                    '<span>' + g.playerB.name + ': ' + lifeB + ' life</span>' +
                '</span>' +
                '<span class="sim-game-expand">&#9654;</span>';

            header.addEventListener('click', () => {
                row.classList.toggle('expanded');
            });

            row.appendChild(header);

            // Turn log
            const logDiv = document.createElement('div');
            logDiv.className = 'sim-turn-log';

            if (g.gameLog && g.gameLog.length > 0) {
                g.gameLog.forEach(turn => {
                    const turnDiv = document.createElement('div');
                    turnDiv.className = 'sim-turn';

                    const turnHeader = document.createElement('div');
                    turnHeader.className = 'sim-turn-header';
                    turnHeader.textContent = 'Turn ' + turn.turn;
                    turnDiv.appendChild(turnHeader);

                    if (turn.phases) {
                        turn.phases.forEach(phase => {
                            const phaseDiv = document.createElement('div');
                            phaseDiv.className = 'sim-phase';

                            const playerLabel = document.createElement('div');
                            playerLabel.className = 'sim-phase-player';
                            playerLabel.textContent = phase.player + "'s turn";
                            phaseDiv.appendChild(playerLabel);

                            if (phase.events && phase.events.length > 0) {
                                phase.events.forEach(ev => {
                                    const evDiv = document.createElement('div');
                                    evDiv.className = 'sim-phase-event';
                                    evDiv.textContent = ev;
                                    phaseDiv.appendChild(evDiv);
                                });
                            } else {
                                const noEv = document.createElement('div');
                                noEv.className = 'sim-phase-event';
                                noEv.textContent = '(no notable actions)';
                                noEv.style.color = '#484f58';
                                phaseDiv.appendChild(noEv);
                            }

                            // Life totals
                            if (phase.lifeAfter) {
                                const lifeDiv = document.createElement('div');
                                lifeDiv.className = 'sim-phase-life';
                                const entries = Object.entries(phase.lifeAfter).map(([n, l]) => n + ': ' + l);
                                lifeDiv.textContent = 'Life — ' + entries.join(' | ');
                                phaseDiv.appendChild(lifeDiv);
                            }

                            // Board state
                            if ((phase.boardA && phase.boardA.length) || (phase.boardB && phase.boardB.length)) {
                                const boardDiv = document.createElement('div');
                                boardDiv.className = 'sim-phase-board';
                                const parts = [];
                                if (phase.boardA && phase.boardA.length)
                                    parts.push('Board A: ' + phase.boardA.join(', '));
                                if (phase.boardB && phase.boardB.length)
                                    parts.push('Board B: ' + phase.boardB.join(', '));
                                boardDiv.textContent = parts.join(' | ');
                                phaseDiv.appendChild(boardDiv);
                            }

                            turnDiv.appendChild(phaseDiv);
                        });
                    }

                    if (turn.event) {
                        const elimDiv = document.createElement('div');
                        elimDiv.className = 'sim-turn-elim';
                        elimDiv.textContent = turn.event;
                        turnDiv.appendChild(elimDiv);
                    }

                    logDiv.appendChild(turnDiv);
                });
            } else {
                logDiv.innerHTML = '<div class="sim-no-logs">Turn logs not recorded for this game</div>';
            }

            row.appendChild(logDiv);
            gamesList.appendChild(row);
        });
    }

    // ── Init ──
    loadDecks();
})();
