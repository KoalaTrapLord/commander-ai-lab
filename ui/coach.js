/**
 * Commander AI Lab — Deck Coach UI v28
 * ═════════════════════════════════════
 * Multi-turn chat with SSE streaming, apply suggestions,
 * cards-like search, enhanced session history.
 */

(function () {
    'use strict';

    const API = window.location.origin;

    // ── State ────────────────────────────────────────────────
    let chatHistory = [];       // [{role, content}]
    let isStreaming = false;
    let currentSessionId = null;
    let sessionCache = {};      // sessionId → full session data
    let expandedSessions = {};  // sessionId → bool
    let dbDecks = [];           // [{id, name}] from /api/decks

    // ── Scryfall Card Hover Preview ─────────────────────────
    const _scryfallImgCache = {};
    let _previewEl = null;

    function _ensurePreviewEl() {
        if (_previewEl) return _previewEl;
        _previewEl = document.createElement('div');
        _previewEl.id = 'coach-card-preview';
        _previewEl.style.display = 'none';
        _previewEl.innerHTML = '<img />';
        document.body.appendChild(_previewEl);
        return _previewEl;
    }

    function _showCardPreview(cardName, evt) {
        const el = _ensurePreviewEl();
        const img = el.querySelector('img');
        if (_scryfallImgCache[cardName]) {
            img.src = _scryfallImgCache[cardName];
        } else {
            img.src = '';
            fetch('https://api.scryfall.com/cards/named?fuzzy=' + encodeURIComponent(cardName))
                .then(r => r.ok ? r.json() : null)
                .then(data => {
                    if (!data) return;
                    const url = (data.image_uris && data.image_uris.normal) || (data.card_faces && data.card_faces[0] && data.card_faces[0].image_uris && data.card_faces[0].image_uris.normal) || '';
                    _scryfallImgCache[cardName] = url;
                    if (el.style.display !== 'none') img.src = url;
                }).catch(() => {});
        }
        el.style.display = 'block';
        _positionPreview(evt);
    }

    function _positionPreview(evt) {
        if (!_previewEl) return;
        _previewEl.style.left = Math.max(0, Math.min(evt.clientX + 20, window.innerWidth - 260)) + 'px';
        _previewEl.style.top = Math.max(0, Math.min(evt.clientY - 150, window.innerHeight - 370)) + 'px';
    }

    function _hideCardPreview() {
        if (_previewEl) _previewEl.style.display = 'none';
    }

    function _attachCardHover(container) {
        container.querySelectorAll('td[data-card-name]').forEach(td => {
            td.addEventListener('mouseenter', e => _showCardPreview(td.dataset.cardName, e));
            td.addEventListener('mousemove', e => _positionPreview(e));
            td.addEventListener('mouseleave', _hideCardPreview);
        });
    }

    // ── DOM References ──────────────────────────────────────
    const deckSelect       = document.getElementById('coach-deck-select');
    const powerSlider      = document.getElementById('coach-power-level');
    const powerValue       = document.getElementById('coach-power-value');
    const metaFocus        = document.getElementById('coach-meta-focus');
    const budgetSelect     = document.getElementById('coach-budget');
    const runBtn           = document.getElementById('coach-run-btn');
    const runHint          = document.getElementById('coach-run-hint');
    const progressEl       = document.getElementById('coach-progress');
    const progressText     = document.getElementById('coach-progress-text');
    const resultsEl        = document.getElementById('coach-results');

    // Status
    const statusLlmDot     = document.querySelector('#status-llm .status-dot');
    const statusLlmValue   = document.getElementById('status-llm-value');
    const statusEmbDot     = document.querySelector('#status-embeddings .status-dot');
    const statusEmbValue   = document.getElementById('status-embeddings-value');
    const statusRepDot     = document.querySelector('#status-reports .status-dot');
    const statusRepValue   = document.getElementById('status-reports-value');

    // Results
    const summaryText      = document.getElementById('coach-summary-text');
    const metaRow          = document.getElementById('coach-meta-row');
    const cutsCount        = document.getElementById('coach-cuts-count');
    const cutsBody         = document.getElementById('coach-cuts-body');
    const cutsAllCheck     = document.getElementById('coach-cuts-all');
    const addsCount        = document.getElementById('coach-adds-count');
    const addsBody         = document.getElementById('coach-adds-body');
    const addsAllCheck     = document.getElementById('coach-adds-all');
    const hintsCard        = document.getElementById('coach-hints-card');
    const hintsList        = document.getElementById('coach-hints-list');
    const manaCard         = document.getElementById('coach-mana-card');
    const manaText         = document.getElementById('coach-mana-text');
    const rawText          = document.getElementById('coach-raw-text');
    const sessionsList     = document.getElementById('coach-sessions-list');
    const genReportsBtn    = document.getElementById('generate-reports-btn');

    // Chat
    const chatMessages     = document.getElementById('coach-chat-messages');
    const chatInput        = document.getElementById('coach-chat-input');
    const chatSendBtn      = document.getElementById('coach-chat-send');
    const chatClearBtn     = document.getElementById('coach-chat-clear');

    // Cards-Like
    const cardslikeInput   = document.getElementById('cardslike-input');
    const cardslikeTopn    = document.getElementById('cardslike-topn');
    const cardslikeSearch  = document.getElementById('cardslike-search-btn');
    const cardslikeResults = document.getElementById('cardslike-results');
    const cardslikeHeader  = document.getElementById('cardslike-header');
    const cardslikeBody    = document.getElementById('cardslike-body');
    const cardslikeArrow   = document.getElementById('cardslike-arrow');

    // Apply
    const applyBtn         = document.getElementById('coach-apply-btn');
    const applyDeckSelect  = document.getElementById('coach-apply-deck-select');
    const applyCountEl     = document.getElementById('coach-apply-count');

    // ── Init ────────────────────────────────────────────────

    init();

    async function init() {
        powerSlider.addEventListener('input', () => {
            powerValue.textContent = powerSlider.value;
        });

        deckSelect.addEventListener('change', () => {
            const hasDeck = deckSelect.value !== '';
            runBtn.disabled = !hasDeck;
            chatSendBtn.disabled = !hasDeck;
            runHint.textContent = hasDeck ? 'Ready to analyze' : 'Select a deck to begin';
        });

        runBtn.addEventListener('click', runCoach);
        genReportsBtn.addEventListener('click', generateReports);

        cutsAllCheck.addEventListener('change', () => {
            cutsBody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = cutsAllCheck.checked;
            });
            updateApplyCount();
        });
        addsAllCheck.addEventListener('change', () => {
            addsBody.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = addsAllCheck.checked;
            });
            updateApplyCount();
        });

        // Chat events
        chatSendBtn.addEventListener('click', sendChatMessage);
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendChatMessage();
            }
        });
        chatInput.addEventListener('input', () => {
            chatSendBtn.disabled = !chatInput.value.trim() || !deckSelect.value;
        });
        chatClearBtn.addEventListener('click', clearChat);

        // Cards-Like
        cardslikeSearch.addEventListener('click', searchCardsLike);
        cardslikeInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') searchCardsLike();
        });
        cardslikeHeader.addEventListener('click', () => {
            cardslikeBody.classList.toggle('collapsed');
            cardslikeArrow.textContent = cardslikeBody.classList.contains('collapsed') ? '\u25B6' : '\u25BC';
        });

        // Apply
        applyBtn.addEventListener('click', applySuggestions);

        // Delegate checkbox changes in tables for apply count
        document.getElementById('coach-cuts-card').addEventListener('change', updateApplyCount);
        document.getElementById('coach-adds-card').addEventListener('change', updateApplyCount);

        // Load data
        await Promise.all([
            checkStatus(),
            loadDecks(),
            loadSessions(),
            loadDbDecks(),
        ]);
    }

    // ── Goals Helper ────────────────────────────────────────

    function getGoals() {
        const goals = {};
        const pl = parseInt(powerSlider.value);
        if (pl) goals.targetPowerLevel = pl;
        if (metaFocus.value) goals.metaFocus = metaFocus.value;
        if (budgetSelect.value) goals.budget = budgetSelect.value;
        const focusAreas = [];
        document.querySelectorAll('.coach-focus-tags input[type="checkbox"]:checked').forEach(cb => {
            focusAreas.push(cb.value);
        });
        if (focusAreas.length > 0) goals.focusAreas = focusAreas;
        return goals;
    }

    // ── Status Check ────────────────────────────────────────

    async function checkStatus() {
        try {
            const res = await fetch(API + '/api/coach/status');
            const data = await res.json();

            if (data.llmConnected) {
                setStatus(statusLlmDot, statusLlmValue, 'ok', data.llmModel || 'Connected');
            } else {
                setStatus(statusLlmDot, statusLlmValue, 'error', data.error || 'Not connected');
            }

            if (data.embeddingsLoaded) {
                setStatus(statusEmbDot, statusEmbValue, 'ok', data.embeddingCards.toLocaleString() + ' cards');
            } else {
                setStatus(statusEmbDot, statusEmbValue, 'warn', 'Not loaded');
            }

            if (data.deckReportsAvailable > 0) {
                setStatus(statusRepDot, statusRepValue, 'ok', data.deckReportsAvailable + ' available');
                genReportsBtn.style.display = 'inline-block';
                genReportsBtn.textContent = 'Rebuild Reports';
            } else {
                setStatus(statusRepDot, statusRepValue, 'warn', 'None \u2014 run simulations first');
                genReportsBtn.style.display = 'inline-block';
                genReportsBtn.textContent = 'Generate Reports';
            }
        } catch (e) {
            setStatus(statusLlmDot, statusLlmValue, 'error', 'Service unavailable');
            setStatus(statusEmbDot, statusEmbValue, 'error', '\u2014');
            setStatus(statusRepDot, statusRepValue, 'error', '\u2014');
        }
    }

    function setStatus(dotEl, valueEl, level, text) {
        dotEl.className = 'status-dot status-' + level;
        valueEl.textContent = text;
    }

    // ── Load Decks ──────────────────────────────────────────

    async function loadDecks() {
        try {
            const res = await fetch(API + '/api/coach/decks');
            const data = await res.json();
            // Backend returns a bare array of objects, not {decks: [...]}
            const decks = Array.isArray(data) ? data : (data.decks || []);

            while (deckSelect.options.length > 1) {
                deckSelect.remove(1);
            }

            if (decks.length === 0) {
                const opt = document.createElement('option');
                opt.disabled = true;
                opt.textContent = 'No decks found \u2014 add decks in Deck Builder first';
                deckSelect.appendChild(opt);
                return;
            }

            // Sort by deck name
            decks.sort((a, b) => {
                const na = (typeof a === 'string' ? a : a.deck_name || '').toLowerCase();
                const nb = (typeof b === 'string' ? b : b.deck_name || '').toLowerCase();
                return na.localeCompare(nb);
            });

            for (const deck of decks) {
                const opt = document.createElement('option');
                if (typeof deck === 'string') {
                    // Legacy: bare string ID
                    opt.value = deck;
                    opt.textContent = deck;
                } else {
                    // Object format: {deck_id, deck_name, commander, has_report, ...}
                    const slug = deck.deck_name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
                    opt.value = slug;
                    opt.textContent = deck.deck_name + (deck.commander ? ' (' + deck.commander + ')' : '');
                }
                deckSelect.appendChild(opt);
            }
        } catch (e) {
            console.error('Failed to load decks:', e);
        }
    }

    // ── Load DB Decks (for Apply) ───────────────────────────

    async function loadDbDecks() {
        try {
            const res = await fetch(API + '/api/decks');
            if (!res.ok) return;
            const data = await res.json();
            dbDecks = data.decks || [];

            while (applyDeckSelect.options.length > 1) {
                applyDeckSelect.remove(1);
            }

            for (const deck of dbDecks) {
                const opt = document.createElement('option');
                opt.value = deck.id;
                opt.textContent = deck.name + (deck.commander ? ' (' + deck.commander + ')' : '');
                applyDeckSelect.appendChild(opt);
            }
        } catch (e) {
            console.error('Failed to load DB decks:', e);
        }
    }

    // ── Load Past Sessions ──────────────────────────────────

    async function loadSessions() {
        try {
            const res = await fetch(API + '/api/coach/sessions');
            const data = await res.json();
            const sessions = data.sessions || [];

            if (sessions.length === 0) {
                sessionsList.innerHTML = '<p class="coach-empty">No coaching sessions yet. Run the coach to get started.</p>';
                return;
            }

            sessionsList.innerHTML = '';
            for (const s of sessions) {
                const item = document.createElement('div');
                item.className = 'coach-session-item';
                item.dataset.sessionId = s.sessionId;

                const timeStr = s.timestamp ? formatTime(s.timestamp) : '';
                const isExpanded = expandedSessions[s.sessionId];

                item.innerHTML =
                    '<div class="coach-session-header" data-sid="' + escHtml(s.sessionId) + '">' +
                        '<span class="coach-session-expand-arrow">' + (isExpanded ? '\u25BC' : '\u25B6') + '</span>' +
                        '<span class="coach-session-deck">' + escHtml(s.deckId) + '</span>' +
                        '<span class="coach-session-summary">' + escHtml(s.summary || '(no summary)') + '</span>' +
                        '<span class="coach-session-meta">' +
                            '<span class="coach-session-cuts">-' + (s.cutsCount || 0) + '</span>' +
                            '<span class="coach-session-adds">+' + (s.addsCount || 0) + '</span>' +
                            '<span class="coach-session-time">' + escHtml(timeStr) + '</span>' +
                        '</span>' +
                    '</div>' +
                    '<div class="coach-session-detail" id="session-detail-' + escHtml(s.sessionId) + '" style="' + (isExpanded ? '' : 'display:none') + '">' +
                        '<div class="coach-session-detail-loading">Loading...</div>' +
                    '</div>';

                // Click handler for expand/collapse
                item.querySelector('.coach-session-header').addEventListener('click', function () {
                    toggleSession(s.sessionId);
                });

                sessionsList.appendChild(item);

                // If previously expanded, load detail
                if (isExpanded && sessionCache[s.sessionId]) {
                    renderSessionDetail(s.sessionId, sessionCache[s.sessionId]);
                }
            }
        } catch (e) {
            console.error('Failed to load sessions:', e);
        }
    }

    async function toggleSession(sessionId) {
        const detailEl = document.getElementById('session-detail-' + sessionId);
        const headerEl = detailEl?.previousElementSibling;
        const arrowEl = headerEl?.querySelector('.coach-session-expand-arrow');

        if (!detailEl) return;

        const wasHidden = detailEl.style.display === 'none';

        if (wasHidden) {
            detailEl.style.display = 'block';
            expandedSessions[sessionId] = true;
            if (arrowEl) arrowEl.textContent = '\u25BC';

            if (!sessionCache[sessionId]) {
                try {
                    const res = await fetch(API + '/api/coach/sessions/' + encodeURIComponent(sessionId));
                    if (!res.ok) throw new Error('Session not found');
                    const session = await res.json();
                    sessionCache[sessionId] = session;
                    renderSessionDetail(sessionId, session);
                } catch (e) {
                    detailEl.innerHTML = '<div class="coach-session-detail-error">Failed to load session details</div>';
                }
            } else {
                renderSessionDetail(sessionId, sessionCache[sessionId]);
            }
        } else {
            detailEl.style.display = 'none';
            expandedSessions[sessionId] = false;
            if (arrowEl) arrowEl.textContent = '\u25B6';
        }
    }

    function renderSessionDetail(sessionId, session) {
        const detailEl = document.getElementById('session-detail-' + sessionId);
        if (!detailEl) return;

        const cuts = session.suggestedCuts || [];
        const adds = session.suggestedAdds || [];

        let html = '<div class="coach-session-detail-inner">';

        // Summary
        if (session.summary) {
            html += '<p class="coach-session-detail-summary">' + escHtml(session.summary) + '</p>';
        }

        // Cuts
        if (cuts.length > 0) {
            html += '<div class="coach-session-detail-group">';
            html += '<span class="coach-session-detail-label">Cuts:</span>';
            html += '<div class="coach-session-pills">';
            for (const cut of cuts) {
                html += '<span class="coach-pill coach-pill-cut" title="' + escHtml(cut.reason || '') + '">' + escHtml(cut.cardName) + '</span>';
            }
            html += '</div></div>';
        }

        // Adds
        if (adds.length > 0) {
            html += '<div class="coach-session-detail-group">';
            html += '<span class="coach-session-detail-label">Adds:</span>';
            html += '<div class="coach-session-pills">';
            for (const add of adds) {
                html += '<span class="coach-pill coach-pill-add" title="' + escHtml(add.reason || '') + '">' + escHtml(add.cardName) + '</span>';
            }
            html += '</div></div>';
        }

        // Load in Chat button
        html += '<div class="coach-session-detail-actions">';
        html += '<button class="btn btn-ghost btn-sm coach-load-chat-btn" data-sid="' + escHtml(sessionId) + '">Load in Chat</button>';
        html += '<button class="btn btn-ghost btn-sm coach-view-full-btn" data-sid="' + escHtml(sessionId) + '">View Full Results</button>';
        html += '</div>';

        html += '</div>';
        detailEl.innerHTML = html;

        // Bind buttons
        detailEl.querySelector('.coach-load-chat-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            loadSessionInChat(sessionId);
        });
        detailEl.querySelector('.coach-view-full-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            displaySession(sessionCache[sessionId]);
            resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }

    function loadSessionInChat(sessionId) {
        const session = sessionCache[sessionId];
        if (!session) return;

        clearChat();

        // Set deck selector if possible
        if (session.deckId) {
            for (let i = 0; i < deckSelect.options.length; i++) {
                if (deckSelect.options[i].value === session.deckId) {
                    deckSelect.value = session.deckId;
                    deckSelect.dispatchEvent(new Event('change'));
                    break;
                }
            }
        }

        // Pre-fill chat with a summary context
        const contextMsg = 'Based on a previous coaching session for this deck, here was the analysis:\n\n' +
            (session.summary || '') + '\n\n' +
            'Suggested cuts: ' + (session.suggestedCuts || []).map(c => c.cardName).join(', ') + '\n' +
            'Suggested adds: ' + (session.suggestedAdds || []).map(a => a.cardName).join(', ');

        chatHistory.push({ role: 'assistant', content: contextMsg });
        appendChatBubble('assistant', contextMsg);

        chatInput.focus();
        showToast('Session loaded into chat', 'success');
    }

    // ── Generate Reports ────────────────────────────────────

    async function generateReports() {
        genReportsBtn.disabled = true;
        genReportsBtn.textContent = 'Generating...';

        try {
            const res = await fetch(API + '/api/coach/reports/generate', { method: 'POST' });
            const data = await res.json();

            if (data.count > 0) {
                genReportsBtn.textContent = data.count + ' reports generated';
                await checkStatus();
                await loadDecks();
            } else {
                genReportsBtn.textContent = 'No results found';
            }
        } catch (e) {
            genReportsBtn.textContent = 'Error: ' + e.message;
        } finally {
            setTimeout(() => {
                genReportsBtn.disabled = false;
                genReportsBtn.textContent = 'Rebuild Reports';
            }, 3000);
        }
    }

    // ── Run Coach (one-shot) ────────────────────────────────

    async function runCoach() {
        const deckId = deckSelect.value;
        if (!deckId) return;

        const goals = getGoals();

        runBtn.disabled = true;
        progressEl.style.display = 'flex';
        progressText.textContent = 'Analyzing deck and consulting LLM... This may take 30-60 seconds.';
        resultsEl.style.display = 'none';

        const prevError = document.querySelector('.coach-error');
        if (prevError) prevError.remove();

        try {
            const res = await fetch(API + '/api/coach/decks/' + encodeURIComponent(deckId), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ goals: goals }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
                throw new Error(err.detail || 'Coach request failed (' + res.status + ')');
            }

            const session = await res.json();
            currentSessionId = session.sessionId || null;
            displaySession(session);
            loadSessions();
        } catch (e) {
            const errDiv = document.createElement('div');
            errDiv.className = 'coach-error';
            errDiv.textContent = 'Coach error: ' + e.message;
            document.querySelector('.coach-config').appendChild(errDiv);
        } finally {
            runBtn.disabled = false;
            progressEl.style.display = 'none';
        }
    }

    // ── Display Session Results ──────────────────────────────

    function displaySession(session) {
        resultsEl.style.display = 'flex';
        currentSessionId = session.sessionId || currentSessionId;

        summaryText.textContent = session.summary || '(No summary provided)';

        metaRow.innerHTML = '';
        if (session.modelUsed) addMetaChip('Model', session.modelUsed);
        if (session.promptTokens) addMetaChip('Prompt', session.promptTokens.toLocaleString() + ' tokens');
        if (session.completionTokens) addMetaChip('Completion', session.completionTokens.toLocaleString() + ' tokens');
        if (session.deckId) addMetaChip('Deck', session.deckId);
        if (session.timestamp) addMetaChip('Time', formatTime(session.timestamp));

        // Cuts table
        const cuts = session.suggestedCuts || [];
        cutsCount.textContent = cuts.length;
        cutsBody.innerHTML = '';
        cutsAllCheck.checked = false;

        for (const cut of cuts) {
            const tr = document.createElement('tr');
            tr.innerHTML =
                '<td><input type="checkbox" data-card="' + escHtml(cut.cardName) + '" /></td>' +
                '<td><span class="coach-card-name">' + escHtml(cut.cardName) + '</span></td>' +
                '<td>' + escHtml(cut.reason) + '</td>' +
                '<td><div class="coach-replacements">' +
                    (cut.replacementOptions || []).map(r =>
                        '<span class="coach-replacement-chip">' + escHtml(r) + '</span>'
                    ).join('') +
                '</div></td>' +
                '<td>' + formatImpact(cut.currentImpactScore) + '</td>';
            tr.querySelector('.coach-card-name').parentElement.dataset.cardName = cut.cardName;
            cutsBody.appendChild(tr);
        }

        // Adds table
        const adds = session.suggestedAdds || [];
        addsCount.textContent = adds.length;
        addsBody.innerHTML = '';
        addsAllCheck.checked = false;

        for (const add of adds) {
            const tr = document.createElement('tr');
            tr.innerHTML =
                '<td><input type="checkbox" data-card="' + escHtml(add.cardName) + '" /></td>' +
                '<td><span class="coach-card-name">' + escHtml(add.cardName) + '</span></td>' +
                '<td>' + (add.role ? '<span class="coach-role-badge">' + escHtml(add.role) + '</span>' : '') + '</td>' +
                '<td>' + escHtml(add.reason) + '</td>' +
                '<td><div class="coach-replacements">' +
                    (add.synergyWith || []).map(s =>
                        '<span class="coach-synergy-chip">' + escHtml(s) + '</span>'
                    ).join('') +
                '</div></td>';
            tr.querySelector('.coach-card-name').parentElement.dataset.cardName = add.cardName;
            addsBody.appendChild(tr);
        }

        // Hints
        const hints = session.heuristicHints || [];
        if (hints.length > 0) {
            hintsCard.style.display = 'block';
            hintsList.innerHTML = '';
            for (const hint of hints) {
                const li = document.createElement('li');
                li.textContent = hint;
                hintsList.appendChild(li);
            }
        } else {
            hintsCard.style.display = 'none';
        }

        // Mana advice
        if (session.manaBaseAdvice) {
            manaCard.style.display = 'block';
            manaText.textContent = session.manaBaseAdvice;
        } else {
            manaCard.style.display = 'none';
        }

        // Raw text
        rawText.textContent = session.rawTextExplanation || session.summary || '(empty)';


        _attachCardHover(cutsBody);
        _attachCardHover(addsBody);
        updateApplyCount();
    }

    // ── Apply Suggestions ───────────────────────────────────

    function updateApplyCount() {
        const cutChecked = cutsBody.querySelectorAll('input[type="checkbox"]:checked');
        const addChecked = addsBody.querySelectorAll('input[type="checkbox"]:checked');
        const total = cutChecked.length + addChecked.length;

        applyCountEl.textContent = cutChecked.length + ' cuts, ' + addChecked.length + ' adds selected';
        applyBtn.disabled = total === 0 || !applyDeckSelect.value;
    }

    applyDeckSelect.addEventListener('change', updateApplyCount);

    async function applySuggestions() {
        const deckId = parseInt(applyDeckSelect.value);
        if (!deckId) {
            showToast('Select a deck to apply suggestions to', 'warning');
            return;
        }

        const acceptedCuts = [];
        cutsBody.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
            const name = cb.dataset.card;
            if (name) acceptedCuts.push(name);
        });

        const acceptedAdds = [];
        addsBody.querySelectorAll('input[type="checkbox"]:checked').forEach(cb => {
            const name = cb.dataset.card;
            if (name) acceptedAdds.push(name);
        });

        if (acceptedCuts.length === 0 && acceptedAdds.length === 0) {
            showToast('No suggestions selected', 'warning');
            return;
        }

        applyBtn.disabled = true;
        applyBtn.textContent = 'Applying...';

        try {
            const res = await fetch(API + '/api/coach/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: currentSessionId || 'manual',
                    deck_id: deckId,
                    accepted_cuts: acceptedCuts,
                    accepted_adds: acceptedAdds,
                }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Apply failed' }));
                throw new Error(err.detail || 'Apply failed');
            }

            const result = await res.json();
            const msg = 'Applied: ' + result.total_cuts + ' cuts, ' + result.total_adds + ' adds' +
                (result.errors.length > 0 ? ' (' + result.errors.length + ' errors)' : '');
            showToast(msg, result.errors.length > 0 ? 'warning' : 'success');

        } catch (e) {
            showToast('Apply error: ' + e.message, 'error');
        } finally {
            applyBtn.disabled = false;
            applyBtn.textContent = 'Apply Suggestions';
            updateApplyCount();
        }
    }

    // ── Multi-turn Chat ─────────────────────────────────────

    async function sendChatMessage() {
        const text = chatInput.value.trim();
        if (!text || !deckSelect.value || isStreaming) return;

        // Add user message
        chatHistory.push({ role: 'user', content: text });
        appendChatBubble('user', text);
        chatInput.value = '';
        chatSendBtn.disabled = true;

        // Show typing indicator
        const typingEl = showTypingIndicator();
        isStreaming = true;

        try {
            const res = await fetch(API + '/api/coach/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    deck_id: deckSelect.value,
                    messages: chatHistory,
                    goals: getGoals(),
                    stream: true,
                }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Chat failed' }));
                throw new Error(err.detail || 'Chat failed (' + res.status + ')');
            }

            // Remove typing indicator, add assistant bubble
            typingEl.remove();
            const bubbleEl = appendChatBubble('assistant', '');
            const contentEl = bubbleEl.querySelector('.coach-chat-bubble-content');

            let fullContent = '';

            // Read SSE stream
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed.startsWith('data: ')) continue;

                    const payload = trimmed.slice(6);
                    if (payload === '[DONE]') break;

                    try {
                        const chunk = JSON.parse(payload);
                        if (chunk.content) {
                            fullContent += chunk.content;
                            contentEl.innerHTML = formatMarkdown(fullContent);
                            scrollChatToBottom();
                        }
                    } catch (e) {
                        // skip malformed chunks
                    }
                }
            }

            // Finalize
            chatHistory.push({ role: 'assistant', content: fullContent });
            contentEl.innerHTML = formatMarkdown(fullContent);
            scrollChatToBottom();

        } catch (e) {
            typingEl.remove();
            appendChatBubble('system', 'Error: ' + e.message);
        } finally {
            isStreaming = false;
            chatSendBtn.disabled = !chatInput.value.trim() || !deckSelect.value;
        }
    }

    function appendChatBubble(role, content) {
        // Remove welcome message
        const welcome = chatMessages.querySelector('.coach-chat-welcome');
        if (welcome) welcome.remove();

        const bubble = document.createElement('div');
        bubble.className = 'coach-chat-bubble coach-chat-' + role;

        const label = role === 'user' ? 'You' : role === 'assistant' ? 'Coach' : 'System';
        bubble.innerHTML =
            '<div class="coach-chat-bubble-label">' + label + '</div>' +
            '<div class="coach-chat-bubble-content">' + (content ? formatMarkdown(content) : '') + '</div>';

        chatMessages.appendChild(bubble);
        scrollChatToBottom();
        return bubble;
    }

    function showTypingIndicator() {
        const el = document.createElement('div');
        el.className = 'coach-chat-typing';
        el.innerHTML =
            '<div class="coach-chat-bubble-label">Coach</div>' +
            '<div class="coach-typing-dots"><span></span><span></span><span></span></div>';
        chatMessages.appendChild(el);
        scrollChatToBottom();
        return el;
    }

    function scrollChatToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function clearChat() {
        chatHistory = [];
        chatMessages.innerHTML =
            '<div class="coach-chat-welcome">' +
                '<div class="coach-chat-welcome-icon">&#129302;</div>' +
                '<p>Select a deck above and ask me anything about your strategy, card choices, or upgrades.</p>' +
            '</div>';
    }

    function formatMarkdown(text) {
        if (!text) return '';
        // Basic markdown: bold, italic, code, line breaks
        return escHtml(text)
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.+?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\n/g, '<br>');
    }

    // ── Cards-Like Search ───────────────────────────────────

    async function searchCardsLike() {
        const card = cardslikeInput.value.trim();
        if (!card) return;

        const activeColors = [];
        document.querySelectorAll('.coach-cardslike-colors .coach-color-pip.active').forEach(btn => {
            activeColors.push(btn.dataset.color);
        });

        const topN = parseInt(cardslikeTopn.value) || 10;

        cardslikeResults.innerHTML = '<div class="coach-cardslike-loading"><div class="spinner"></div> Searching embeddings...</div>';

        try {
            let url = API + '/api/coach/cards-like?card=' + encodeURIComponent(card) + '&top_n=' + topN;
            if (activeColors.length > 0) {
                url += '&colors=' + activeColors.join('');
            }

            const res = await fetch(url);
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Search failed' }));
                throw new Error(err.detail || 'Search failed');
            }

            const data = await res.json();
            const results = data.results || [];

            if (results.length === 0) {
                cardslikeResults.innerHTML = '<div class="coach-cardslike-empty">No similar cards found</div>';
                return;
            }

            cardslikeResults.innerHTML = '';
            for (const card of results) {
                const div = document.createElement('div');
                div.className = 'coach-cardslike-card';

                const simPct = Math.round(card.similarity * 100);
                const ownedBadge = card.owned_qty > 0
                    ? '<span class="coach-cl-owned">' + card.owned_qty + ' owned</span>'
                    : '<span class="coach-cl-unowned">not owned</span>';
                const price = card.tcg_price ? '$' + Number(card.tcg_price).toFixed(2) : '';

                div.innerHTML =
                    '<div class="coach-cl-top">' +
                        '<span class="coach-cl-name">' + escHtml(card.name) + '</span>' +
                        '<span class="coach-cl-sim">' + simPct + '%</span>' +
                    '</div>' +
                    '<div class="coach-cl-meta">' +
                        '<span class="coach-cl-type">' + escHtml(card.types || '') + '</span>' +
                        (card.mana_cost ? '<span class="coach-cl-mana">' + escHtml(card.mana_cost) + '</span>' : '') +
                        ownedBadge +
                        (price ? '<span class="coach-cl-price">' + price + '</span>' : '') +
                    '</div>' +
                    (card.text ? '<div class="coach-cl-text">' + escHtml(card.text) + '</div>' : '') +
                    '<div class="coach-cl-actions">' +
                        '<button class="btn btn-ghost btn-xs coach-cl-chat-btn">Add to Chat</button>' +
                    '</div>';

                div.querySelector('.coach-cl-chat-btn').addEventListener('click', () => {
                    chatInput.value += (chatInput.value ? ' ' : '') + card.name;
                    chatInput.focus();
                    showToast(card.name + ' added to chat input', 'success');
                });

                cardslikeResults.appendChild(div);
            }
        } catch (e) {
            cardslikeResults.innerHTML = '<div class="coach-cardslike-empty">Error: ' + escHtml(e.message) + '</div>';
        }
    }

    // Color pip toggle
    document.querySelectorAll('.coach-cardslike-colors .coach-color-pip').forEach(btn => {
        btn.addEventListener('click', () => btn.classList.toggle('active'));
    });

    // ── Toast ───────────────────────────────────────────────

    function showToast(message, type) {
        const container = document.getElementById('coach-toast-container');
        const toast = document.createElement('div');
        toast.className = 'coach-toast coach-toast-' + (type || 'info');
        toast.textContent = message;
        container.appendChild(toast);

        setTimeout(() => toast.classList.add('coach-toast-show'), 10);
        setTimeout(() => {
            toast.classList.remove('coach-toast-show');
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    }

    // ── Helpers ─────────────────────────────────────────────

    function addMetaChip(label, value) {
        const chip = document.createElement('span');
        chip.className = 'coach-meta-chip';
        chip.innerHTML = '<strong>' + escHtml(label) + ':</strong> ' + escHtml(value);
        metaRow.appendChild(chip);
    }

    function formatImpact(score) {
        if (score === undefined || score === null) {
            return '<span class="coach-impact coach-impact-neutral">\u2014</span>';
        }
        const fixed = score.toFixed(3);
        if (score < -0.01) {
            return '<span class="coach-impact coach-impact-negative">' + fixed + '</span>';
        } else if (score > 0.01) {
            return '<span class="coach-impact coach-impact-positive">+' + fixed + '</span>';
        } else {
            return '<span class="coach-impact coach-impact-neutral">' + fixed + '</span>';
        }
    }

    function formatTime(isoStr) {
        try {
            const d = new Date(isoStr);
            return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch {
            return isoStr;
        }
    }

    function escHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

})();
