/**
 * Commander AI Lab — Auto Deck Generator V3 UI
 * ═══════════════════════════════════════════════
 *
 * V3 Endpoints:
 *   GET   /api/deck/v3/status              — check V3 generator status
 *   GET   /api/deck-generator/commander-search  — autocomplete commanders
 *   POST  /api/deck/v3/generate            — generate deck (local AI structured output)
 *   POST  /api/deck/v3/commit              — generate + save to Deck Builder
 *   POST  /api/deck/v3/export/csv          — export as CSV
 *   POST  /api/deck/v3/export/dck          — export as Forge .dck
 *   POST  /api/deck/v3/export/moxfield     — export in Moxfield paste format
 *   POST  /api/deck/v3/export/shopping     — shopping list of missing cards
 */

const DeckGenerator = (() => {
    'use strict';

    const API_BASE = window.location.origin;
    const DEBOUNCE_MS = 350;

    const COLOR_MAP = {
        W: { label: 'W', cls: 'dg-pip-W' },
        U: { label: 'U', cls: 'dg-pip-U' },
        B: { label: 'B', cls: 'dg-pip-B' },
        R: { label: 'R', cls: 'dg-pip-R' },
        G: { label: 'G', cls: 'dg-pip-G' },
        C: { label: 'C', cls: 'dg-pip-C' },
    };

    const TYPE_ORDER = ['Creature', 'Instant', 'Sorcery', 'Artifact', 'Enchantment', 'Planeswalker', 'Land', 'Battle', 'Other'];
    const TYPE_ICONS = {
        'Creature': '🐉', 'Instant': '⚡', 'Sorcery': '🌀', 'Artifact': '🔧',
        'Enchantment': '✨', 'Planeswalker': '🌟', 'Land': '🏔', 'Battle': '⚔',
        'Other': '🃏',
    };

    const STATUS_BADGES = {
        owned: { label: 'Owned', cls: 'dg-badge-owned' },
        substituted: { label: 'Substituted', cls: 'dg-badge-substituted' },
        missing: { label: 'Missing', cls: 'dg-badge-missing' },
    };

    // ── State ──────────────────────────────────────────────
    let state = {
        commander: null,
        targetBracket: 3,
        previewResult: null,
        lastRequestBody: null,
        isLoading: false,
        v3Ready: false,
    };

    let searchTimeout = null;

    // ── Progress bar state ──────────────────────────────
    const PROGRESS_PHASES = [
        { at: 0,  pct: 5,   msg: 'Connecting to AI model...' },
        { at: 3,  pct: 10,  msg: 'Resolving commander on Scryfall...' },
        { at: 6,  pct: 18,  msg: 'Building collection summary...' },
        { at: 10, pct: 25,  msg: 'Sending prompt to LLM...' },
        { at: 20, pct: 40,  msg: 'AI is building the 99...' },
        { at: 35, pct: 55,  msg: 'Selecting cards and filling slots...' },
        { at: 50, pct: 65,  msg: 'Running smart substitution...' },
        { at: 70, pct: 78,  msg: 'Cross-referencing with collection...' },
        { at: 90, pct: 88,  msg: 'Almost there — finalizing deck...' },
        { at: 110, pct: 93, msg: 'Still working — large model can take a moment...' },
    ];
    let _progressInterval = null;
    let _progressStart = 0;

    function startProgress() {
        _progressStart = Date.now();
        const wrap = $('dg-progress-wrap');
        const fill = $('dg-progress-fill');
        const phase = $('dg-progress-phase');
        const elapsed = $('dg-progress-elapsed');
        if (!wrap) return;
        wrap.style.display = 'block';
        fill.style.width = '0%';
        phase.textContent = '';
        elapsed.textContent = '0s elapsed';
        let lastPhaseIdx = -1;
        _progressInterval = setInterval(() => {
            const secs = Math.floor((Date.now() - _progressStart) / 1000);
            elapsed.textContent = secs + 's elapsed';
            for (let i = PROGRESS_PHASES.length - 1; i >= 0; i--) {
                if (secs >= PROGRESS_PHASES[i].at) {
                    fill.style.width = PROGRESS_PHASES[i].pct + '%';
                    if (i !== lastPhaseIdx) {
                        phase.textContent = PROGRESS_PHASES[i].msg;
                        logMessage(PROGRESS_PHASES[i].msg, 'info');
                        lastPhaseIdx = i;
                    }
                    break;
                }
            }
        }, 1000);
    }

    function stopProgress(success) {
        if (_progressInterval) {
            clearInterval(_progressInterval);
            _progressInterval = null;
        }
        const fill = $('dg-progress-fill');
        const phase = $('dg-progress-phase');
        const elapsed = $('dg-progress-elapsed');
        if (fill) fill.style.width = success ? '100%' : '0%';
        if (phase) phase.textContent = success ? 'Done!' : 'Failed';
        const secs = Math.floor((Date.now() - _progressStart) / 1000);
        if (elapsed) elapsed.textContent = secs + 's total';
    }

        // ── Omit Cards (chips) ─────────────────────────────
    let omitCards = [];

    function addOmitCard(name) {
        const trimmed = name.trim();
        if (!trimmed) return;
        if (omitCards.some(c => c.toLowerCase() === trimmed.toLowerCase())) return;
        omitCards.push(trimmed);
        renderOmitChips();
    }

    function removeOmitCard(idx) {
        omitCards.splice(idx, 1);
        renderOmitChips();
    }

    function renderOmitChips() {
        const container = $('dg-omit-chips');
        if (!container) return;
        container.innerHTML = omitCards.map((name, i) =>
            '<span class="dg-chip">' +
                escHtml(name) +
                '<span class="dg-chip-x" data-idx="' + i + '">&times;</span>' +
            '</span>'
        ).join('');
        container.querySelectorAll('.dg-chip-x').forEach(el => {
            el.addEventListener('click', () => removeOmitCard(parseInt(el.dataset.idx, 10)));
        });
    }

    const $ = (id) => document.getElementById(id);

    // ── Init ────────────────────────────────────────────────
    async function init() {
        await checkV3Status();
        bindEvents();
        checkQueryParams();
    }

    async function checkV3Status() {
        try {
            const resp = await fetch(API_BASE + '/api/deck/v3/status');
            const data = await resp.json();
            state.v3Ready = data.initialized;
            if (!state.v3Ready) {
                // Warn but do not block — local/Ollama mode may still work
                console.warn('V3 status: not initialized. Error:', data.error || 'unknown');
                toast('V3 generator not ready — check that the local AI model (gpt-oss:20b) is running via Ollama', 'warning');
            }
        } catch (e) {
            console.warn('V3 status check failed:', e);
        }
    }

    function bindEvents() {
        // Commander search
        const input = $('dg-commander-input');
        input.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            const q = input.value.trim();
            if (q.length < 2) { hideDropdown(); return; }
            searchTimeout = setTimeout(() => searchCommander(q), DEBOUNCE_MS);
        });

        input.addEventListener('focus', () => {
            const q = input.value.trim();
            if (q.length >= 2) searchCommander(q);
        });

        document.addEventListener('click', (e) => {
            const wrap = document.querySelector('.dg-commander-search-wrap');
            if (wrap && !wrap.contains(e.target)) hideDropdown();
        });

        $('dg-commander-clear').addEventListener('click', clearCommander);

        // Bracket buttons
        document.querySelectorAll('.dg-bracket-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.dg-bracket-btn').forEach(b => b.classList.remove('dg-bracket-active'));
                btn.classList.add('dg-bracket-active');
                state.targetBracket = parseInt(btn.dataset.bracket, 10);
            });
        });

        // Generate & save
        $('dg-preview-btn').addEventListener('click', generateDeck);
        $('dg-save-btn').addEventListener('click', commitDeck);
        $('dg-regenerate-btn').addEventListener('click', generateDeck);

        // Export buttons
        $('dg-export-csv').addEventListener('click', () => exportDeck('csv'));
        $('dg-export-dck').addEventListener('click', () => exportDeck('dck'));
        $('dg-export-moxfield').addEventListener('click', () => exportMoxfield());
        $('dg-export-shopping').addEventListener('click', () => exportShopping());

                // Omit cards chips input
        const omitInput = $('dg-omit-input');
        if (omitInput) {
            omitInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    addOmitCard(omitInput.value);
                    omitInput.value = '';
                }
            });
        }
        const omitWrap = $('dg-omit-wrap');
        if (omitWrap) {
            omitWrap.addEventListener('click', () => omitInput && omitInput.focus());
        }
    }

    function checkQueryParams() {
        const params = new URLSearchParams(window.location.search);
        const name = params.get('commander');
        if (name) {
            $('dg-commander-input').value = name;
            searchCommander(name);
        }
    }

    // ── Build Request Body ──────────────────────────────────
    function buildRequestBody() {
        const budget = parseFloat($('dg-budget').value) || null;
        return {
            commander_name: state.commander.name,
            strategy: $('dg-strategy').value.trim(),
            target_bracket: state.targetBracket,
            budget_usd: budget,
            budget_mode: $('dg-budget-mode').value,
            omit_cards: omitCards.slice(),
            use_collection: $('dg-use-collection').checked,
            run_substitution: $('dg-substitution').checked,
            model: $('dg-model').value,
            deck_name: $('dg-deck-name').value.trim() || '',
        };
    }

    // ── Commander Search ────────────────────────────────────
    function positionDropdown() {
        const input = $('dg-commander-input');
        const dropdown = $('dg-commander-dropdown');
        const rect = input.getBoundingClientRect();
        dropdown.style.top = (rect.bottom + 4) + 'px';
        dropdown.style.left = rect.left + 'px';
        dropdown.style.width = rect.width + 'px';
    }

    async function searchCommander(q) {
        const dropdown = $('dg-commander-dropdown');
        dropdown.innerHTML = '<div class="dg-dropdown-loading">Searching...</div>';
        dropdown.classList.add('open');
        positionDropdown();

        try {
            const resp = await fetch(API_BASE + '/api/deck-generator/commander-search?q=' + encodeURIComponent(q));
            const data = await resp.json();
            renderDropdown(data.results || []);
        } catch (e) {
            dropdown.innerHTML = '<div class="dg-dropdown-empty">Search failed</div>';
        }
    }

    function renderDropdown(results) {
        const dropdown = $('dg-commander-dropdown');

        if (results.length === 0) {
            dropdown.innerHTML = '<div class="dg-dropdown-empty">No legendary creatures found</div>';
            return;
        }

        dropdown.innerHTML = results.map((r, idx) => {
            const colors = (r.color_identity || [])
                .map(c => COLOR_MAP[c] ? '<span class="dg-color-pip ' + COLOR_MAP[c].cls + '">' + COLOR_MAP[c].label + '</span>' : '')
                .join('');

            const badge = r.in_collection
                ? '<span class="dg-dropdown-item-badge dg-badge-owned">Owned</span>'
                : '<span class="dg-dropdown-item-badge dg-badge-scryfall">Scryfall</span>';

            const imgSrc = r.image_url ? r.image_url.replace('version=normal', 'version=small') : '';
            const imgTag = imgSrc
                ? '<img class="dg-dropdown-item-img" src="' + imgSrc + '" alt="" loading="lazy" />'
                : '<div class="dg-dropdown-item-img" style="background:var(--lab-surface)"></div>';

            return '<div class="dg-dropdown-item" data-idx="' + idx + '">'
                + imgTag
                + '<div class="dg-dropdown-item-info">'
                + '  <div class="dg-dropdown-item-name">' + escHtml(r.name) + '</div>'
                + '  <div class="dg-dropdown-item-type">' + escHtml(r.type_line || '') + '</div>'
                + '</div>'
                + '<div style="display:flex;gap:3px;align-items:center">' + colors + '</div>'
                + badge
                + '</div>';
        }).join('');

        dropdown.querySelectorAll('.dg-dropdown-item').forEach(el => {
            el.addEventListener('click', () => {
                selectCommander(results[parseInt(el.dataset.idx, 10)]);
                hideDropdown();
            });
        });
    }

    function selectCommander(cmdr) {
        state.commander = cmdr;
        $('dg-commander-input').style.display = 'none';
        $('dg-commander-selected').style.display = 'block';
        $('dg-commander-name').textContent = cmdr.name;
        $('dg-commander-type').textContent = cmdr.type_line || '';

        $('dg-commander-colors').innerHTML = (cmdr.color_identity || [])
            .map(c => COLOR_MAP[c] ? '<span class="dg-color-pip ' + COLOR_MAP[c].cls + '">' + COLOR_MAP[c].label + '</span>' : '')
            .join('');

        const img = $('dg-commander-img');
        if (cmdr.image_url) {
            var imgUrl = cmdr.image_url;
            if (imgUrl.indexOf('version=small') !== -1) {
                imgUrl = imgUrl.replace('version=small', 'version=normal');
            } else if (imgUrl.indexOf('version=') === -1 && imgUrl.indexOf('?') !== -1) {
                imgUrl += '&version=normal';
            } else if (imgUrl.indexOf('version=') === -1) {
                imgUrl += '?version=normal';
            }
            img.src = imgUrl;
            img.style.display = 'block';
        } else {
            img.style.display = 'none';
        }

        $('dg-preview-btn').disabled = false;

                // Auto-fill deck name if empty
        const deckNameInput = $('dg-deck-name');
        if (deckNameInput && !deckNameInput.value.trim()) {
            deckNameInput.value = 'Auto - ' + cmdr.name;
        }
    }

    function clearCommander() {
        state.commander = null;
        $('dg-commander-input').style.display = '';
        $('dg-commander-input').value = '';
        $('dg-commander-selected').style.display = 'none';
        $('dg-preview-btn').disabled = true;
    }

    function hideDropdown() {
        $('dg-commander-dropdown').classList.remove('open');
    }

    // -- Conversation Log Helper --
    function logMessage(msg, type = 'info') {
        const log = $('dg-conversation-log');
        if (!log) return;
        const entry = document.createElement('div');
        entry.className = 'dg-log-entry dg-log-' + type;
        const ts = new Date().toLocaleTimeString();
        entry.innerHTML = '<span class="dg-log-ts">[' + ts + ']</span> ' + msg;
        log.appendChild(entry);
        log.scrollTop = log.scrollHeight;
    }

    function clearLog() {
        const log = $('dg-conversation-log');
        if (!log) return;
        log.innerHTML = '';
    }

    // ── Generate Deck ───────────────────────────────────────
    async function generateDeck() {
        clearLog();
        logMessage('Connecting to local AI model (gpt-oss:20b)...', 'info');
        if (!state.commander) { toast('Select a commander first', 'error'); return; }
        // Non-blocking warning only — local Ollama mode does not require v3Ready
        if (!state.v3Ready) {
            logMessage('Warning: V3 status check failed. Attempting generation anyway via local AI...', 'warning');
        }
        logMessage('Building request body with commander: <b>' + state.commander.name + '</b>', 'info');

        setLoading(true, 'Generating deck via Local AI...');
        startProgress();

        const body = buildRequestBody();
        logMessage('Sending request to AI model... this may take a moment.', 'info');
        state.lastRequestBody = body;

        try {
            const resp = await fetch(API_BASE + '/api/deck/v3/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.error || err.detail || 'Generation failed');
            }

            state.previewResult = await resp.json();
            logMessage('AI response received! Processing deck data...', 'success');

            const stats = state.previewResult.stats || {};
            const cardCount = (stats.total_cards || 0);
            logMessage('Deck generated: <b>' + cardCount + ' cards</b> | $' + (stats.total_price_usd || 0).toFixed(2) + ' estimated', 'success');
                        stopProgress(true);
            renderResults(state.previewResult);

            toast('Deck generated: ' + (stats.total_cards || 0) + ' cards | $' + (stats.total_price_usd || 0), 'success');
        } catch (e) {
                    stopProgress(false);
            toast(e.message || 'Generation failed', 'error');
            logMessage('Error: ' + (e.message || 'Unknown error'), 'error');
            setLoading(false);
        }
    }

    function setLoading(loading, text) {
        state.isLoading = loading;
        $('dg-empty-state').style.display = 'none';
        $('dg-loading').style.display = loading ? 'flex' : 'none';
        $('dg-results').style.display = loading ? 'none' : 'none';
        $('dg-preview-btn').disabled = loading || !state.commander;
        if (text) $('dg-loading-text').textContent = text;
    }

    // ── Render Results ──────────────────────────────────────
    function renderResults(result) {
        $('dg-loading').style.display = 'none';
        $('dg-results').style.display = 'block';
        $('dg-preview-btn').disabled = false;

        renderStrategyBar(result);
        renderStatsBar(result);
        renderSubstitutionSummary(result);
        renderCardGroups(result);
    }

    function renderStrategyBar(result) {
        const bar = $('dg-strategy-bar');
        const bracket = result.bracket || {};
        const archetype = result.archetype || '';
        const strategy = result.strategy_summary || '';

        bar.innerHTML = '<div class="dg-strategy-info">'
            + '<span class="dg-bracket-badge dg-bracket-' + (bracket.level || 0) + '">B' + (bracket.level || '?') + '</span>'
            + '<span class="dg-archetype-badge">' + escHtml(archetype) + '</span>'
            + '<span class="dg-strategy-text">' + escHtml(strategy) + '</span>'
            + '</div>'
            + (bracket.reasoning ? '<div class="dg-bracket-reasoning">' + escHtml(bracket.reasoning) + '</div>' : '')
            + (bracket.game_changers && bracket.game_changers.length
                ? '<div class="dg-game-changers">Game Changers: ' + bracket.game_changers.map(c => '<span class="dg-gc-chip">' + escHtml(c) + '</span>').join('') + '</div>'
                : '');
    }

    function renderStatsBar(result) {
        const stats = result.stats || {};
        const container = $('dg-stats-bar');

        const chips = [
            chipHtml('Total', stats.total_cards || 0, ''),
            chipHtml('Owned', (stats.by_status || {}).owned || 0, 'dg-stat-owned'),
            chipHtml('Subbed', (stats.by_status || {}).substituted || 0, 'dg-stat-substituted'),
            chipHtml('Missing', (stats.by_status || {}).missing || 0, 'dg-stat-missing'),
            chipHtml('Lands', stats.land_count || 0, ''),
            chipHtml('$' + (stats.total_price_usd || 0).toFixed(0), 'Total', 'dg-stat-price'),
        ];

        container.innerHTML = chips.join('');
    }

    function chipHtml(label, num, cls) {
        return '<div class="dg-stat-chip ' + cls + '">'
            + '<span class="dg-stat-num">' + num + '</span>'
            + '<span class="dg-stat-label">' + label + '</span>'
            + '</div>';
    }

    function renderSubstitutionSummary(result) {
        const el = $('dg-sub-summary');
        const sub = result.substitution_stats;
        if (!sub) { el.style.display = 'none'; return; }

        el.style.display = 'block';
        el.innerHTML = '<div class="dg-sub-bar">'
            + '<span class="dg-sub-stat dg-sub-owned">' + sub.owned + ' owned</span>'
            + '<span class="dg-sub-stat dg-sub-substituted">' + sub.substituted + ' substituted</span>'
            + '<span class="dg-sub-stat dg-sub-missing">' + sub.missing + ' still missing</span>'
            + '</div>';
    }

    function renderCardGroups(result) {
        const container = $('dg-card-groups');
        const cards = result.cards || [];
        const commander = result.commander;

        const groups = {};
        for (const card of cards) {
            const cat = card.category || 'Other';
            if (!groups[cat]) groups[cat] = [];
            groups[cat].push(card);
        }

        const sortedTypes = TYPE_ORDER.filter(t => groups[t] && groups[t].length > 0);
        for (const t of Object.keys(groups)) {
            if (!sortedTypes.includes(t)) sortedTypes.push(t);
        }

        let html = '';

        if (commander) {
            html += '<div class="dg-card-group">'
                + '<div class="dg-group-header">'
                + '<span class="dg-group-title">⚔ Commander</span>'
                + '<span class="dg-group-count">1</span>'
                + '</div>'
                + '<div class="dg-group-body">'
                + '<div class="dg-card-row dg-card-row-commander">'
                + '<span class="dg-card-row-name" style="font-weight:600;color:#fff">' + escHtml(commander.name) + '</span>'
                + '<span class="dg-card-row-source dg-src-collection">Commander</span>'
                + '</div>'
                + '</div></div>';
        }

        for (const type of sortedTypes) {
            const groupCards = groups[type];
            if (!groupCards || groupCards.length === 0) continue;

            groupCards.sort((a, b) => (a.name || '').localeCompare(b.name || ''));

            const icon = TYPE_ICONS[type] || '🃏';
            html += '<div class="dg-card-group">'
                + '<div class="dg-group-header" data-type="' + type + '">'
                + '<span class="dg-group-title">' + icon + ' ' + escHtml(type) + '</span>'
                + '<span class="dg-group-count">' + groupCards.reduce(function(s,c){ return s + (c.count || 1); }, 0) + '</span>'
                + '</div>'
                + '<div class="dg-group-body" data-group="' + type + '">';

            for (const card of groupCards) {
                html += renderCardRow(card);
            }

            html += '</div></div>';
        }

        container.innerHTML = html;

        container.querySelectorAll('.dg-group-header').forEach(header => {
            header.addEventListener('click', () => {
                const type = header.dataset.type;
                if (!type) return;
                const body = container.querySelector('.dg-group-body[data-group="' + type + '"]');
                if (body) body.classList.toggle('collapsed');
            });
        });
    }

    function renderCardRow(card) {
        const statusInfo = STATUS_BADGES[card.status] || STATUS_BADGES.missing;
        const statusBadge = '<span class="dg-card-status ' + statusInfo.cls + '">' + statusInfo.label + '</span>';

        const roleTags = (card.role_tags || []).slice(0, 3)
            .map(r => '<span class="dg-role-chip">' + escHtml(r) + '</span>')
            .join('');

        let subHtml = '';
        if (card.status === 'substituted' && card.selected_substitute) {
            subHtml = '<div class="dg-card-sub-line">'
                + '<span class="dg-sub-arrow">→</span> '
                + '<span class="dg-sub-name">' + escHtml(card.selected_substitute) + '</span>'
                + '</div>';
        } else if (card.status === 'missing' && card.alternatives && card.alternatives.length > 0) {
            subHtml = '<div class="dg-card-sub-line dg-sub-suggestions">'
                + '<span class="dg-sub-label">Alternatives:</span> '
                + card.alternatives.slice(0, 3).map(a =>
                    '<span class="dg-alt-chip" title="' + escAttr(a.reason || '') + '">'
                    + escHtml(a.name) + ' (' + (a.similarity_score * 100).toFixed(0) + '%)'
                    + '</span>'
                ).join('')
                + '</div>';
        }

        const price = card.estimated_price_usd
            ? '<span class="dg-card-price">$' + card.estimated_price_usd.toFixed(2) + '</span>'
            : '';

        return '<div class="dg-card-row dg-card-status-' + card.status + '">'
            + '<div class="dg-card-row-main">'
            + '<span class="dg-card-row-name">' + ((card.count || 1) > 1 ? '<span class="dg-card-count">' + card.count + 'x</span> ' : '') + escHtml(card.name) + '</span>'
            + '<span class="dg-card-row-roles">' + roleTags + '</span>'
            + statusBadge
            + price
            + '</div>'
            + (card.reason ? '<div class="dg-card-reason">' + escHtml(card.reason) + '</div>' : '')
            + subHtml
            + '</div>';
    }

    // ── Commit Deck ─────────────────────────────────────────
    async function commitDeck() {
        if (!state.commander) { toast('No commander selected', 'error'); return; }

        $('dg-save-btn').disabled = true;
        $('dg-save-btn').textContent = 'Saving...';

        try {
            const body = state.lastRequestBody || buildRequestBody();
            const resp = await fetch(API_BASE + '/api/deck/v3/commit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.error || err.detail || 'Save failed');
            }

            const result = await resp.json();
            toast('Deck saved: ' + (result.deck_name || 'Unknown'), 'success');

            setTimeout(() => {
                window.location.href = 'deckbuilder.html?deck_id=' + result.deck_id;
            }, 1200);
        } catch (e) {
            toast(e.message || 'Save failed', 'error');
        } finally {
            $('dg-save-btn').disabled = false;
            $('dg-save-btn').innerHTML = '<span class="dg-btn-icon">💾</span> Save to Deck Builder';
        }
    }

    // ── Exports ─────────────────────────────────────────────
    async function exportDeck(format) {
        if (!state.commander) { toast('Generate a deck first', 'error'); return; }

        const body = state.lastRequestBody || buildRequestBody();

        try {
            const resp = await fetch(API_BASE + '/api/deck/v3/export/' + format, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!resp.ok) throw new Error('Export failed');

            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = (state.commander.name || 'deck').replace(/\s+/g, '_') + '.' + (format === 'csv' ? 'csv' : 'dck');
            a.click();
            URL.revokeObjectURL(url);

            toast('Exported ' + format.toUpperCase(), 'success');
        } catch (e) {
            toast(e.message || 'Export failed', 'error');
        }
    }

    async function exportMoxfield() {
        if (!state.commander) { toast('Generate a deck first', 'error'); return; }

        const body = state.lastRequestBody || buildRequestBody();

        try {
            const resp = await fetch(API_BASE + '/api/deck/v3/export/moxfield', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            const data = await resp.json();
            if (data.content) {
                await navigator.clipboard.writeText(data.content);
                toast('Moxfield deck copied to clipboard', 'success');
            }
        } catch (e) {
            toast('Moxfield export failed', 'error');
        }
    }

    async function exportShopping() {
        if (!state.commander) { toast('Generate a deck first', 'error'); return; }

        const body = state.lastRequestBody || buildRequestBody();

        try {
            const resp = await fetch(API_BASE + '/api/deck/v3/export/shopping', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            const data = await resp.json();
            const list = data.shopping_list || [];

            if (list.length === 0) {
                toast('All cards are owned — nothing to buy', 'success');
                return;
            }

            const lines = ['Shopping List — ' + (data.commander || 'Deck'), ''];
            for (const item of list) {
                lines.push(item.count + 'x ' + item.name + ' ($' + (item.estimated_price_usd || 0).toFixed(2) + ') — ' + item.category);
            }
            lines.push('', 'Total: ' + list.length + ' cards, ~$' + (data.estimated_cost_usd || 0).toFixed(2));

            await navigator.clipboard.writeText(lines.join('\n'));
            toast('Shopping list copied (' + list.length + ' cards, ~$' + (data.estimated_cost_usd || 0).toFixed(0) + ')', 'success');
        } catch (e) {
            toast('Shopping list failed', 'error');
        }
    }

    // ── Toast ───────────────────────────────────────────────
    function toast(msg, type) {
        type = type || 'info';
        const container = $('dg-toast-container');
        const el = document.createElement('div');
        el.className = 'dg-toast dg-toast-' + type;
        el.textContent = msg;
        container.appendChild(el);
        setTimeout(() => el.remove(), 4000);
    }

    // ── Helpers ─────────────────────────────────────────────
    function escHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function escAttr(str) {
        return str.replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    return { init };
})();

document.addEventListener('DOMContentLoaded', () => {
    DeckGenerator.init();
});
